import time
import asyncio
from typing import Awaitable, Coroutine, Generator


async def asleep(duration):
    start = time.perf_counter()
    print(f'Start sleeping at {start} s')
    await asyncio.sleep(duration)
    print(f'Sleep for {time.perf_counter() - start} s')


coroutineObj = asleep(1)
print(f"{asyncio.iscoroutinefunction(asleep)=}\n"
      f"{asyncio.iscoroutine(coroutineObj)=}\n"
      f"{hasattr(coroutineObj, '__await__')=}\n"
      f"{asyncio.iscoroutine(coroutineObj.__await__)=}\n"
      f"{asyncio.iscoroutine(coroutineObj.__await__())=}\n"
      f"{asyncio.iscoroutinefunction(coroutineObj.__await__)=}\n"
      f"{isinstance(coroutineObj, Awaitable)=}\n"
      f"{isinstance(coroutineObj, Coroutine)=}\n"
      f"{isinstance(coroutineObj.__await__(), Generator)=}")


class generatorSleep:
    def __init__(self, duration):
        self.duration = duration

    def __await__(self):
        start = time.perf_counter()
        print(f'Start {type(self).__name__} at {start} s')
        while time.perf_counter() - start < self.duration:
            yield
        print(f'Sleep for {time.perf_counter() - start} s')


class yieldfromSleep:
    def __init__(self, duration):
        self.duration = duration

    def __await__(self):
        start = time.perf_counter()
        print(f'Start {type(self).__name__} at {start} s')
        task = asyncio.create_task(asyncio.sleep(self.duration))
        yield from task
        print(f'Sleep for {time.perf_counter() - start} s')


async def main():
    print('Sequential sleep')
    await generatorSleep(1)
    await generatorSleep(2)
    print('Concurrent sleep')
    await asyncio.gather(generatorSleep(1), generatorSleep(2))
    print(f'Finished at {time.perf_counter()} s')
    await yieldfromSleep(1)


if __name__ == '__main__':
    asyncio.run(main())
