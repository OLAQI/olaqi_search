import logging
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import event_message_type, EventMessageType, command
from astrbot.api.provider import ProviderRequest
from typing import List, Dict
import json
import os
import requests
from astrbot.api.all import Plain, MessageChain  # 从 astrbot.api.all 导入 Plain 和 MessageChain

logger = logging.getLogger("astrbot")

@register("olaqi_search", "OLAQI", "位置查询插件", "1.0.0", "https://github.com/OLAQI/olaqi_search")
class LocationQueriesPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.amap_api_key = config.get("amap_api_key", "")
        self.fixed_location = config.get("fixed_location", "")
        self.fixed_location_coords = self._get_coords(self.fixed_location) if self.fixed_location else None

    @command("so")
    async def search_nearby(self, event: AstrMessageEvent):
        """查询附近的某个地点"""
        query = event.message_str.split(" ", 1)[1]
        location = self.fixed_location or self._get_location_from_event(event)
        coords = self._get_coords(location)
        if not coords:
            await event.send("无法获取定位，请检查配置。")
            return

        nearby_info = await self._search_poi(coords, query)
        summary = await self._generate_summary(nearby_info)
        await event.send(MessageChain([Plain(f"附近的 {query} 信息：\n{summary}")]))

    @command("go")
    async def get_distance_and_time(self, event: AstrMessageEvent):
        """查询固定位置到指定位置的距离和预计时间"""
        parts = event.message_str.split(" ")
        if len(parts) == 2:
            destination = parts[1]
            origin = self.fixed_location
        elif len(parts) == 4 and parts[2] == "to":
            origin, destination = parts[1], parts[3]
        else:
            await event.send("命令格式错误，请使用 /go <起点> 或 /go <起点> to <终点>。")
            return

        origin_coords = self._get_coords(origin)
        destination_coords = self._get_coords(destination)
        if not origin_coords or not destination_coords:
            await event.send("无法获取定位，请检查配置。")
            return

        distance, duration = await self._get_distance_and_time(origin_coords, destination_coords)
        await event.send(MessageChain([Plain(f"{origin} 到 {destination} 的距离是 {distance} 米，预计时间 {duration} 分钟。")]))

    @command("dd")
    async def get_traffic_info(self, event: AstrMessageEvent):
        """查询固定位置到指定位置的路况信息"""
        parts = event.message_str.split(" ")
        if len(parts) == 2:
            destination = parts[1]
            origin = self.fixed_location
        elif len(parts) == 4 and parts[2] == "to":
            origin, destination = parts[1], parts[3]
        else:
            await event.send("命令格式错误，请使用 /dd <起点> 或 /dd <起点> to <终点>。")
            return

        origin_coords = self._get_coords(origin)
        destination_coords = self._get_coords(destination)
        if not origin_coords or not destination_coords:
            await event.send("无法获取定位，请检查配置。")
            return

        traffic_info = await self._get_traffic_info(origin_coords, destination_coords)
        summary = await self._generate_summary(traffic_info)
        await event.send(MessageChain([Plain(f"{origin} 到 {destination} 的路况信息：\n{summary}")]))

    async def _get_coords(self, address: str) -> str:
        """根据地址获取经纬度坐标"""
        url = f"https://restapi.amap.com/v3/geocode/geo?address={address}&key={self.amap_api_key}"
        response = requests.get(url)
        data = response.json()
        if data["status"] == "1" and data["count"] > 0:
            return data["geocodes"][0]["location"]
        return ""

    async def _search_poi(self, coords: str, keyword: str) -> List[Dict]:
        """查询附近的 POI 信息"""
        url = f"https://restapi.amap.com/v3/place/text?key={self.amap_api_key}&keywords={keyword}&location={coords}&radius=1000&output=json"
        response = requests.get(url)
        data = response.json()
        if data["status"] == "1":
            return data["pois"]
        return []

    async def _get_distance_and_time(self, origin: str, destination: str) -> (int, int):
        """查询两点之间的距离和预计时间"""
        url = f"https://restapi.amap.com/v3/direction/driving?origin={origin}&destination={destination}&key={self.amap_api_key}"
        response = requests.get(url)
        data = response.json()
        if data["status"] == "1":
            route = data["route"]["paths"][0]
            return route["distance"], route["duration"]
        return 0, 0

    async def _get_traffic_info(self, origin: str, destination: str) -> str:
        """查询两点之间的路况信息"""
        url = f"https://restapi.amap.com/v3/direction/driving?origin={origin}&destination={destination}&key={self.amap_api_key}"
        response = requests.get(url)
        data = response.json()
        if data["status"] == "1":
            return data["route"]["desc"]
        return "无法获取路况信息，请检查配置。"

    async def _generate_summary(self, data: List[Dict] or str) -> str:
        """使用 LLM 生成总结"""
        provider = self.context.get_using_provider()
        if provider:
            if isinstance(data, list):
                data_str = "\n".join([f"{poi['name']} - {poi['address']}" for poi in data])
            else:
                data_str = data
            prompt = f"请根据以下信息生成一个简洁的总结：\n{data_str}"
            response = await provider.text_chat(prompt, session_id="location_summary")
            return response.completion_text
        else:
            return "无法生成总结，请检查LLM配置。"

    def _get_location_from_event(self, event: AstrMessageEvent) -> str:
        """从事件中获取位置信息"""
        # 这里可以根据实际情况从事件中提取位置信息
        return self.fixed_location
