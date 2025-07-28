import asyncio
import websockets
import time

async def simple_test():
    uri = "ws://localhost:5876/ws/test_delay"
    async with websockets.connect(uri) as websocket:
        # 发送简单消息
        start = time.time()
        await websocket.send('{"message": "test"}')
        
        # 接收响应
        response = await websocket.recv()
        end = time.time()
        
        print(f"Round trip time: {(end - start) * 1000:.2f}ms")
        print(f"Response: {response}")

asyncio.run(simple_test())
