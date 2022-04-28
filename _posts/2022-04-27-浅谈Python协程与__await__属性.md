---
layout: post
categories: blog
author: Aureliano
title:  浅谈Python协程与__await__属性
date:   2022-04-27 18:28:00 -0500
tags: [python, asyncio]
comments: True
---

## 协程简介

众所周知，Python在3.5版本引入了`async/await`语法，在此之前协程由`yield/yield from`实现。协程的使用方法此处不赘述，说白了就是以`await`关键字调用被`async def`
定义的函数。我觉得`asyncio`应该是所有网络程序的标配，不过初次接触的人可能会被异步程序的跳转搞糊涂，觉得`asyncio`就是莫名其妙的`goto`
。对底层实现和控制流程感兴趣的，可以参考[这篇文章](https://www.yixuebiancheng.com/article/89674.html)。

## 阐明概念

本文尝试厘清`asyncio`里的几个关键概念。首先引进几个包，用`async def`定义`asleep`函数，包装一下`asyncio.sleep`。

{% highlight python %}

    import time
    import asyncio
    from typing import Awaitable, Coroutine, Generator
    
    
    async def asleep(duration):
        start = time.perf_counter()
        print(f'Start sleeping at {start} s')
        await asyncio.sleep(duration)
        print(f'Sleep for {time.perf_counter() - start} s')

{% endhighlight %}

### Coroutine Function

以`async def`定义的函数是Coroutine Function，这一点可以用`asyncio.iscoroutinefunction`验证。与普通函数不同，给协程函数赋参并不会执行函数里的代码，而是返回一个Coroutine
Object。比如

{% highlight python %}
coroutineObj = asleep(1)
{% endhighlight %}

### Coroutine Object

协程对象（或直接简称协程）可以用`asyncio.iscoroutine`验证，其类型是`typing`里的`Awaitable`和`Coroutine`，结果如下。实现异步并发，就是在Coroutine Object前面以`await`
关键字调用，如`await coroutineObj`，这时候协程才真正开始执行。

```
asyncio.iscoroutinefunction(asleep)=True
asyncio.iscoroutine(coroutineObj)=True
isinstance(coroutineObj, Awaitable)=True
isinstance(coroutineObj, Coroutine)=True
```

### `__await__` Attribute

协程对象能被`await`关键字调用，是因为它们拥有`__await__`属性，该方法返回的，不是协程函数也不是协程对象，而是一个生成器，验证结果如下。

```
hasattr(coroutineObj, '__await__')=True
asyncio.iscoroutine(coroutineObj.__await__)=False
asyncio.iscoroutine(coroutineObj.__await__())=False
asyncio.iscoroutinefunction(coroutineObj.__await__)=False
isinstance(coroutineObj.__await__(), Generator)=True
```

## 重新实现协程

如果把这三个概念理清楚了，我认为基本上掌握`asyncio`了。为了让理解更透彻，下面尝试重新实现一个协程，以达到和用`async def`定义的`asleep`一样的效果。

{% highlight python %}

    class generatorSleep:
        def __init__(self, duration):
        self.duration = duration

        def __await__(self):
            start = time.perf_counter()
            print(f'Start {type(self).__name__} at {start} s')
            while time.perf_counter() - start < self.duration:
                yield
            print(f'Sleep for {time.perf_counter() - start} s')

{% endhighlight %}

首先测试代码如下

{% highlight python %}

    async def main():
        print('Sequential sleep')
        await generatorSleep(1)
        await generatorSleep(2)
        print('Concurrent sleep')
        await asyncio.gather(generatorSleep(1), generatorSleep(2))
        print(f'Finished at {time.perf_counter()} s')
    
    if __name__ == '__main__':
        asyncio.run(main())

{% endhighlight %}

测试结果如下，的确实现了异步睡眠。

```
Sequential sleep
Start generatorSleep at 0.2971936 s
Sleep for 1.0000021000000001 s
Start generatorSleep at 1.297214 s
Sleep for 2.0000028 s
Concurrent sleep
Start generatorSleep at 3.2973044 s
Start generatorSleep at 3.2973155 s
Sleep for 1.0000049999999998 s
Sleep for 2.0000032 s
Finished at 5.297353 s
```

这里定义的类`generatorSleep`其实就相当于以`async def`定义的Coroutine Function，给其赋参后生成了`generatorSleep`实例，相当于Coroutine Object。
该实例可被`await`关键字调用，因为其实现了`__await__`方法，而`__await__`方法返回的则是一个生成器。

## yield from奇技淫巧

需要注意的是，在`__await__`方法里我选择了以一个`while`循环加`yield`的方式来构建生成器，而不是以`yield from asyncio.sleep(self.duration)`的方式去嵌套生成器。
如果是后者，解析器会弹出

```
TypeError: cannot 'yield from' a coroutine object in a non-coroutine generator
```

异常，因为从3.5开始Python刻意在语法上对`await`和`yield from`关键字作出了区分，协程不再能被`yield from`调用，而是必须`await`。不过实际上，
存在一个workaround，就是先用`asyncio.Task`包裹协程，再以`yield from`调用，以下代码可行，`asyncio.gather`同理。

{% highlight python %}

    class yieldfromSleep:
        def __init__(self, duration):
            self.duration = duration
    
        def __await__(self):
            start = time.perf_counter()
            print(f'Start {type(self).__name__} at {start} s')
            task = asyncio.create_task(asyncio.sleep(self.duration))
            yield from task
            print(f'Sleep for {time.perf_counter() - start} s')

    await yieldfromSleep(1)

{% endhighlight %}

至此，一个简陋版的Python协程以类的形式被重新构造，而不需要用`async def`来定义协程函数。

## 异步构造函数

理清了协程的构造，接下来介绍如何以异步的方式构造一个类的实例。如果一个类实例的初始化需要从网络获取数据，且需要请求不止一个API，以异步的方式构造实例就能缩短时间，提升效率。

既然协程的异步都来自`__await__`方法，且该方法可以用`yield from`的形式来调用其他协程，那事情就简单了。`__init__`该怎么写还是怎么写，
不过把需要异步并发创建的属性搬到`__await__`里，在`__await__`里用`yield from`调用异步网络API，事情就解决了。例子如下

{% highlight python %}

    class DataClass:
        def __init__(self, **kwargs):
            self.local = kwargs

        def __await__(self):
            task = asyncio.create_task(aiohttp.ClientSession.request(url))
            self.data = yield from task
            return self

    dataInstance = await DataClass(**kwargs)

{% endhighlight %}

其实现和上面的重构协程差不多，当`DataClass(**kwargs)`被`await`调用时，先用`__init__`方法构建实例，然后`await`会调用该实例的`__await__`方法，
剩下的实例属性则在`__await__`里被异步创建。不过要注意的是，单纯睡眠时`__await__`不用返回结果，而在这里需要返回`self`，
否则`dataInstance`是不会被赋值构建好的实例。

## 结语

[测试代码在此](https://raw.githubusercontent.com/Aureliano90/Aureliano90.github.io/main/samples/__await__.py)。希望本文能帮读者理清Python asyncio里的几个关键概念。