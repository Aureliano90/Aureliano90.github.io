---
layout: post
categories: blog
author: Aureliano
title:  在Python中实现客户端限制API访问速率
date:   2022-04-19 00:28:00 -0500
tags: [python, asyncio, semaphore]
comments: True
---

## 限速算法

交易所或网站一般会限制每个API的访问速率，在服务器端限流主要有漏桶和令牌桶两种实现方式，参考[限流算法之漏桶与令牌桶](http://ponder.work/2021/05/30/leaky-bucket-and-token-bucket/)
。具体实现也有许多现成工具，此处不赘述。

不过据我观察与测试，OKEx
API的限流方式既不是漏桶也不是令牌桶，经搜索发现其应是滑动窗口算法。以其[历史资金费API](https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP)
为例，[文档](https://www.okx.com/docs-v5/zh/#rest-api-public-data-get-funding-rate-history)里写着：

```
限速： 10次/2s
限速规则：IP +instrumentID
```

经验证其规则如下：

```
∀ t ∈ R, 在t到t+2之间请求数 ≤ 10
```

说中文就是：在时间轴上任意2秒内，请求数小于等于10个。比如当`t ∈ [0, 2]`，10个请求可以全在`[0, 0.1]`内发出，此后从`t=0.1`到`t=2`
的所有请求都会被拒绝。假设第一次请求发生在`t=0`，第二次请求在`t=0.1`，则第11次请求必须在`t=2`之后，第12次必须在`t=2.1`以后。因为允许并发请求，这显然不是漏桶算法。由于在`t ∈ [0.1, 2]`
不再补充令牌，这应该也不是令牌桶算法。

如果客户端根据漏桶算法限制API访问速率，则需要以0.2秒的间隔发送请求，这虽然符合了OKEx的要求，但无法并发，牺牲了效率。

若是遵从令牌桶算法，桶的容量应为10个令牌，因为最多同时可以发10个请求，若如此令牌添加速率就成了问题。假设每x秒添加一个令牌，且在`t=0`一下子发送了10个请求，要是`x < 2`
，会出现2秒内发送了11次请求，被服务器拒绝。要是`x ≥ 2`，则无法达到平均0.2秒一次的访问速率。如果规定`x = 0.2`，则令牌桶容量必须为1，变成和漏桶一样，无法并发。

不过反过来，要是一种算法满足OKEx限速的要求，则其必然满足令牌桶算法的要求，假设桶的容量为10而令牌添加速率为每0.2秒一个，因为服务器在任意2秒内至少可以处理10次请求。

## 实现方式

关于如何在Python里进行客户端限流，网上已有许多文章，不过没有一个是我满意的。大部分都提到了Semaphore，其中很多只是用Semaphore限制了并发连接数，
并没有限制请求速率。而触及限制请求速率的，其实现非常粗糙，在asyncio框架下，大致如下：

{% highlight python %}

    sem = asyncio.Semaphore(10)

    async def example(query):
        async with sem:
            await request(query)
            await asyncio.sleep(2)

{% endhighlight %}

这种实现，虽然保证了2秒内不多于10次请求，但每次请求都要额外多等2秒，即便一共只有1个请求。敏锐的读者可能已经察觉到这里有优化空间，如果改成
`Semaphore(5)`和`sleep(1)`，同样是10次/2s，但每个协程只需要等1秒。如果改成`Semaphore(2)`和`sleep(0.4)`，每个协程只需等0.4秒。
如果是`Semaphore(1)`和`sleep(0.2)`，则只需等0.2秒。但这样还哪有并发，要asyncio干什么？完全变成了漏桶模式。

经过摸索，在我的OKEx程序中，访问速率限制由以下定制类实现，继承自`asyncio.Semaphore`。

{% highlight python %}
class REST_Semaphore(asyncio.Semaphore):
"""A custom semaphore to be used with REST API with velocity limit under asyncio
"""

    def __init__(self, value: int, interval: int):
        """控制REST API访问速率

        :param value: API limit
        :param interval: Reset interval
        """
        super().__init__(value)
        # Queue of inquiry timestamps
        self._inquiries = collections.deque(maxlen=value)
        self._loop = asyncio.get_event_loop()
        self._interval = interval

    def __repr__(self):
        return f'API velocity: {self._inquiries.maxlen} inquiries/{self._interval}s'

    async def acquire(self):
        await super().acquire()
        if self._inquiries:
            timelapse = time.monotonic() - self._inquiries.popleft()
            # Wait until interval has passed since the first inquiry in queue returned.
            if timelapse < self._interval:
                await asyncio.sleep(self._interval - timelapse)
        return True

    def release(self):
        self._inquiries.append(time.monotonic())
        super().release()

{% endhighlight %}

其思路为，在`self._value`从最大并发数降到0前，`super().acquire`不阻塞。假设`value = 10`，且同时有11个协程调用`self.acquire`
，在第11个协程调用时`self._value = 0`，直到第1个请求返回，在`self.release`里把`self._value`加1且把时间戳加入`self._inquiries`队列。
随后第11个协程退出`super().acquire`，调用`self._inquiries.popleft`获取第1个请求的时间戳，等到第1个请求返回的2秒后再发送请求。
在`release`里而不是`acquire`里`self._inquiries.append`
是因为如果记录的是发送时间，第1个请求传输到服务器的时间有可能比第11个请求的传输时间长，这样服务器接收到第11个请求的时间可能在第1个的2秒内。

有了这个类后，可以给每个API对应的方法安排一个类属性，分别控制不同API的访问速率。比如在`publicAPI`类里添加一个类属性等于`REST_Semaphore(10, 2)`
，在`get_historical_funding_rate`里以`async with`调用，以下代码不再发生超速。否则即便把50改成11也会报错。

{% highlight python %}

    okex = await OKExAPI()

    for _ in range(50):
        tasks.append(asyncio.create_task(okex.publicAPI.get_historical_funding_rate('BTC-USDT-SWAP')))
    res = await gather(*tasks)

{% endhighlight %}

在`multiprocessing`下，一样可以限制多进程的并发数及访问速率，只需在创建进程时把`p_Semaphore`实例传入，以上下文管理器调用。实现如下，多线程类似。

{% highlight python %}
class p_Semaphore(ContextManager):
"""A custom semaphore to be used with REST API with velocity limit by processes
"""

    def __init__(self, value: int, interval: int):
        """控制REST API并发连接

        :param value: API limit
        :param interval: Reset interval
        """
        self._interval = interval
        self._sem = multiprocessing.Semaphore(value)
        # Queue of inquiry timestamps
        self._inquiries = multiprocessing.Queue()

    def __enter__(self):
        self._sem.acquire()
        if self._inquiries.qsize():
            timelapse = time.monotonic() - self._inquiries.get()
            # Wait until interval has passed since the first inquiry in queue returned.
            if timelapse < self._interval:
                time.sleep(self._interval - timelapse)
        return True

    def __exit__(self, *args):
        self._inquiries.put(time.monotonic())
        self._sem.release()

{% endhighlight %}

## 总结

要限制并发连接数和访问速率，只需在每次调用API时以上下文管理器调用以上Semaphore实例。创建实例时`value`参数为最大并发数，`interval`为刷新间隔。
以上实现遵从滑动窗口算法，且完全兼容令牌桶算法，只需让`value`等于令牌桶容量，令`value / interval`等于令牌填充速度。