import paho.mqtt.client as mqtt
import re
import asyncio
import aiomqtt
import ssl
import time

from typing import List

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketDisconnect
from queue import Queue

app = FastAPI()

#----below Webpage for viewing communication while testing -----

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
    </head>
    <body>
        <h1>WebSocket Chat</h1>
        <h2>Your ID: <span id="ws-id"></span></h2>
        <form action="" onsubmit="setClientId(event)">
            <input type="text" id="ClientId" autocomplete="on"/>
            <button>Set Client Id</button>
        </form>
        <form action="" onsubmit="fireCommand(event)">
            <input type="text" id="Command" autocomplete="off"/>
            <button>Get Values</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var client_id = Date.now()
            document.querySelector("#ws-id").textContent = client_id;
            var ws = new WebSocket(`ws://localhost:8000/ws/${client_id}`);
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                var content = document.createTextNode(event.data)
                message.appendChild(content)
                messages.appendChild(message)
            };

            ws.onclose = function(event) { alert("Websocket Closed"); };
            ws.onopen = function(event) { alert("Web socket opened!"); };
            ws.onerror = function(event) { alert("Error in Websocket"); };
            
            function setClientId(event) {
                var clientId = document.getElementById("ClientId")
                ws.send("id:"+clientId.value)
                //input.value = ''
                event.preventDefault()
            };
            function fireCommand(event) {
                var command = document.getElementById("Command")
                ws.send("cmd:"+command.value)
                event.preventDefault()
            };
        </script>
    </body>
</html>
"""


class WatchDog: #https://stackoverflow.com/questions/44891761/how-to-wait-for-object-to-change-state

    def __init__(self):
        self.latestmsg = ''
        self.channel=''
        self.websocket:WebSocket = None
        self._WaitforMsg = asyncio.Event()

    def MsgReceived(self):
        self._WaitforMsg.set()

    def NewMsgAwait(self):
        self._WaitforMsg.clear()
        self.latestmsg=''

    async def ws_receive(self):
        self.msg = await self.websocket.receive_text()
        self.channel="WEBSOCKET"
        return self.latestmsg

    async def MsgWatchDog(self):
        await self._WaitforMsg.wait()
        self._WaitforMsg.clear()
        return self.latestmsg

    @property
    async def msg(self):
        await self._WaitforMsg.wait()
        return self.latestmsg

    @msg.setter
    def msg(self, value):
        self.latestmsg = value
        self.MsgReceived()

data = WatchDog()

#-----------------Websocket Manager------------------------

class WS_ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        #----- Websocket setup-----
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


wsManager = WS_ConnectionManager()

#-------------MQTT handler------------
mqttc = mqtt.Client(client_id="FASTAPI")#, clean_session=True, userdata=None, protocol=mqtt.MQTTv311, transport="tcp")

class MQTT_ConnectionManager:
    def __init__(self):
        self.active_topics: List[List[WebSocket,str]] = []

    #------MQTT client set up------
    def client_create(self):
        mqttc.tls_set(ca_certs="E:/Communication Cerificates/ca.crt", certfile="E:/Communication Cerificates/client.crt", keyfile="E:/Communication Cerificates/client.key", cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_1, ciphers=None)
        mqttc.username_pw_set("_______", password="_______") #put id& password of mqtt
        mqttc.tls_insecure_set(True)# this is very fatal, but while new certificate with Domain-Name create, this will be turned off
        mqttc.on_message = self.onMessage
    
    def connect(self, host="__.__.__.__",port=____,keepalive=60):# put ip & port of mqtt server
        if not mqttc.is_connected():
            mqttc.connect(host, port, keepalive)
            mqttc.loop_start()

    def subscribe(self,websocket:WebSocket, topicId:str):#this to be checked
        print("Connected with result code " )
        self.active_topics.append([websocket, topicId])
        print(self.active_topics)
        mqttc.subscribe(topicId)

    def unscribe(self, websocket:WebSocket, topicId:str):
        self.active_topics.remove([websocket, topicId])
        (result, mid)=mqttc.unsubscribe(topicId)

    def onMessage(self, client, userdata, msg):#this to be checked
        print(msg.topic+" "+str(msg.payload))
        message = re.search("'(.*)'", str(msg.payload))  # why re package used?
        data.channel=msg.topic
        data.msg = message.group(1)

    def disconnect(self):
        mqttc.loop_stop(force=True)
        if mqttc.is_connected():
            mqttc.disconnect()
    
    def publish(self,topic,message):
        mqttc.publish(topic,message)

mqttManager = MQTT_ConnectionManager()
mqttManager.client_create()

#----------ASYNCIO Loop creation--------
l = asyncio.get_event_loop()
asyncio.set_event_loop(l)

#----------server Listners--------------
@app.get("/")
async def get():
    return HTMLResponse(html)

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):

    await wsManager.connect(websocket)
    data.websocket=websocket

    mqttManager.connect()

    try:
        while True:
            ws=l.create_task(data.ws_receive())
            wd=l.create_task(data.MsgWatchDog())
            print(f"thread count : {len(asyncio.all_tasks())}")
            await asyncio.wait([wd])
            #await wsManager.send_personal_message(f"You wrote: {data._msg}", websocket)
            if data.channel=="WEBSOCKET":
                m = data.latestmsg.split(":")
                print(m)
                if m[0]=="id":
                    topicId=m[1]
                    mqttManager.subscribe(websocket,m[1]+"/out")
                    await wsManager.broadcast(f"MQTT #{topicId}/out is subscribed")
                else:
                    command=m[1]
                    mqttManager.publish(topicId+"/in",command)
                    await wsManager.broadcast(f"MQTT-command on #{topicId}/in : {command}")
            else:
                await wsManager.broadcast(f"Client #{data.channel} says: {data.latestmsg} with channel")

            data.NewMsgAwait()
            #break

    except WebSocketDisconnect:
        print('except block...')
        l.close()
        mqttManager.unscribe(websocket, client_id)
        mqttManager.disconnect()
        await wsManager.broadcast(f"Client #{client_id} left the chat")
        wsManager.disconnect(websocket)
        
    finally:
        print('finally block...')
        l.close()
        mqttManager.disconnect()
        wsManager.disconnect(websocket)
