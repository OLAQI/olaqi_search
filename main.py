import logging
import requests
from typing import Dict, Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api.event.filter import command

logger = logging.getLogger("astrbot")

@register("olaqi_search", "OLAQI", "高德地图周边搜索插件", "1.0.1", "https://github.com/OLAQI/olaqi_search")
class GaodePOIPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        # 确保存储固定位置
        if "fixed_location" not in self.config:
            self.config["fixed_location"] = {}
        # 确保存储高德Key
        if "amap_api_key" not in self.config:
            self.config["amap_api_key"] = ""

    @command("so")
    async def search_poi(self, event: AstrMessageEvent):
        """搜索周边POI"""
        api_key = self.config.get("amap_api_key")
        if not api_key:
            await event.send([Plain("未配置高德API Key，请在管理面板中设置。")])
            return

        parts = event.message_str.split("so", 1)
        if len(parts) < 2:
            await event.send([Plain("请使用 /so <关键词> 的格式搜索。")])
            return

        keyword = parts[1].strip()

        # 如果用户未设置固定位置,则给出提示
        if not self.config.get("fixed_location"):
            await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
            return

        location = self.config["fixed_location"].get("location")
        if not location:
            await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
            return

        # 构造请求 URL（周边搜索）
        url = (
            f"https://restapi.amap.com/v3/place/around?key={api_key}"
            f"&location={location}"
            f"&keywords={keyword}"
            "&radius=3000"  # 搜索半径，可配置
            "&offset=20"     # 每页数量，可配置
            "&page=1"       # 页码
            "&extensions=all" # 详细信息
        )

        try:
            response = requests.get(url)
            response.raise_for_status()  # 检查请求状态
            data = response.json()

            if data["status"] == "1":
                pois = data.get("pois", [])
                if pois:
                    # 使用LLM总结
                    poi_info_list = [
                        f"{poi['name']} (距离：{poi.get('distance', '未知')}米): {poi.get('address', '未知地址')}"
                        for poi in pois
                    ]
                    poi_info_str = "\n".join(poi_info_list)

                    provider = self.context.get_using_provider()
                    if provider:
                        prompt = f"请总结以下周边地点信息：\n{poi_info_str}\n请用简洁的语言总结，并适当分类（如美食、酒店等）。"
                        response = await provider.text_chat(prompt, session_id=event.session_id)
                        summary = response.completion_text
                        await event.send([Plain(f"找到以下地点：\n{summary}")])
                    else:
                        formatted_pois = "\n".join([
                            f"{poi['name']} (距离：{poi.get('distance', '未知')}米): {poi.get('address', '未知地址')}"
                            for poi in pois
                        ])
                        await event.send([Plain(f"找到以下地点：\n{formatted_pois}")]) # 不使用LLM
                else:
                    await event.send([Plain("附近没有找到相关地点。")])
            else:
                await event.send([Plain(f"搜索失败: {data.get('info', '未知错误')}。")])

        except requests.RequestException as e:
            await event.send([Plain(f"请求失败: {e}")])

    @command("go")
    async def travel_time(self, event: AstrMessageEvent):
        """计算行程时间"""
        api_key = self.config.get("amap_api_key")
        if not api_key:
            await event.send([Plain("未配置高德API Key，请在管理面板中设置。")])
            return

        parts = event.message_str.split("go", 1)[1].strip().split("to")
        origin_name = parts[0].strip()
        destination_name = parts[1].strip() if len(parts) > 1 else ""

        # 如果只输入一个地点则默认起点为用户设置位置
        if not destination_name:
            destination_name = origin_name
            # 如果用户未设置固定位置,则给出提示
            if not self.config.get("fixed_location"):
                await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
                return

            origin = self.config["fixed_location"].get("location")
            if not origin:
                await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
                return
            origin_name = self.config["fixed_location"].get("name", "我的位置")  # 获取固定位置名称
        else:
            # 先搜索起点
            origin = await self.get_location_from_keyword(api_key, origin_name)
            if not origin:
                await event.send([Plain(f"找不到起点：{origin_name}")])
                return

        # 搜索终点
        destination = await self.get_location_from_keyword(api_key, destination_name)
        if not destination:
            await event.send([Plain(f"找不到终点：{destination_name}")])
            return

        # 路径规划
        url = (
            f"https://restapi.amap.com/v3/direction/driving?key={api_key}" # 默认驾车
            f"&origin={origin}"
            f"&destination={destination}"
            "&extensions=base"  # all会返回详细路况，base返回基本信息
        )

        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if data["status"] == "1":
                route = data["route"]
                distance = int(route["paths"][0]["distance"]) / 1000  # 转为公里
                duration = int(route["paths"][0]["duration"]) / 60   # 转为分钟

                await event.send([Plain(
                    f"从 {origin_name} 到 {destination_name} 的距离约为 {distance:.2f} 公里，预计驾车时间 {duration:.0f} 分钟。"
                )])
            else:
                await event.send([Plain(f"查询失败: {data.get('info', '未知错误')}")])
        except requests.RequestException as e:
            await event.send([Plain(f"请求失败: {e}")])

    async def get_location_from_keyword(self, api_key: str, keyword: str) -> str | None:
        """通过关键字获取经纬度"""
        # 先搜索
        search_url = f"https://restapi.amap.com/v3/place/text?key={api_key}&keywords={keyword}&citylimit=true"
        try:
            response = requests.get(search_url)
            response.raise_for_status()
            data = response.json()
            if data["status"] == "1" and data["pois"]:
                location = data["pois"][0]["location"]
                return location
            else:
                return None  # 没找到
        except requests.RequestException:
            return None

    @command("dd")
    async def traffic_info(self, event: AstrMessageEvent):
        """路况信息"""
        api_key = self.config.get("amap_api_key")
        if not api_key:
            await event.send([Plain("未配置高德API Key，请在管理面板中设置。")])
            return

        parts = event.message_str.split("dd", 1)[1].strip().split("to")
        origin_name = parts[0].strip()
        destination_name = parts[1].strip() if len(parts) > 1 else ""

        # 如果只输入一个地点则默认起点为用户设置位置
        if not destination_name:
            destination_name = origin_name
            # 如果用户未设置固定位置,则给出提示
            if not self.config.get("fixed_location"):
                await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
                return

            origin = self.config["fixed_location"].get("location")
            if not origin:
                await event.send([Plain("请先使用 /setlocation 命令设置您的固定位置。")])
                return
            origin_name = self.config["fixed_location"].get("name", "我的位置")  # 获取固定位置名称
        else:
            # 先搜索起点
            origin = await self.get_location_from_keyword(api_key, origin_name)
            if not origin:
                await event.send([Plain(f"找不到起点：{origin_name}")])
                return

        # 搜索终点
        destination = await self.get_location_from_keyword(api_key, destination_name)
        if not destination:
            await event.send([Plain(f"找不到终点：{destination_name}")])
            return

        # 路径规划,要路况需要返回详细信息
        url = (
            f"https://restapi.amap.com/v3/direction/driving?key={api_key}" # 默认驾车
            f"&origin={origin}"
            f"&destination={destination}"
            "&extensions=all"
        )

        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if data["status"] == "1":
                route = data["route"]
                distance = int(route["paths"][0]["distance"]) / 1000  # 转为公里
                duration = int(route["paths"][0]["duration"]) / 60   # 转为分钟
                traffic_lights = int(route["paths"][0]["traffic_lights"]) # 红绿灯数量
                # 路况信息
                steps = route["paths"][0]["steps"]
                traffic_info = ""
                for step in steps:
                    status = step.get("traffic_condition", "未知")
                    traffic_info += f"{step['instruction']}，路况：{status} \n"

                await event.send([Plain(
                    f"从 {origin_name} 到 {destination_name} 的距离约为 {distance:.2f} 公里，预计驾车时间 {duration:.0f} 分钟，路过{traffic_lights}个红绿灯\n{traffic_info}。"
                )])
            else:
                await event.send([Plain(f"查询失败: {data.get('info', '未知错误')}")])
        except requests.RequestException as e:
            await event.send([Plain(f"请求失败: {e}")])

    @command("setlocation")
    async def set_location(self, event: AstrMessageEvent):
        """设置固定位置"""
        api_key = self.config.get("amap_api_key")
        if not api_key:
            await event.send([Plain("未配置高德API Key，请在管理面板中设置。")])
            return

        location_name = event.message_str.split("setlocation", 1)[1].strip()

        if not location_name:
            await event.send([Plain("请使用 /setlocation <地点名称> 的格式设置固定位置。")])
            return

        location = await self.get_location_from_keyword(api_key, location_name)
        if not location:
            await event.send([Plain("未找到该位置,请检查输入是否有误")])
            return

        # 保存到配置
        self.config["fixed_location"]["location"] = location
        self.config["fixed_location"]["name"] = location_name

        await event.send([Plain(f"已将您的固定位置设置为：{location_name} ({location})")])
