from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import *
import json
import asyncio
import datetime 
import aiohttp
import os
import tempfile
from zoneinfo import ZoneInfo  # 导入 ZoneInfo 用于处理时区
import chinese_calendar as calendar  # 导入 chinese_calendar 库

@register("moyuren", "quirrel", "一个简单的摸鱼人日历插件", "1.3.7")
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.enabled = config.get("enabled", True)  # 从配置文件读取摸鱼日历定时任务启用状态
        self.temp_dir = tempfile.mkdtemp()  # 创建临时目录
        self.config = config
        logger.info(f"插件配置信息: {self.config}")
        self.moyu_api_url = config.get("moyu_api_url") or "https://api.52vmy.cn/api/wl/moyu"
        logger.info(f"当前使用的摸鱼日历API URL: {self.moyu_api_url}")
        self.default_timezone = config.get("default_timezone")
        try:
            self.user_custom_timezone = ZoneInfo(self.default_timezone)
        except Exception:
            self.user_custom_timezone = ZoneInfo('Asia/Shanghai')
        self.user_custom_time = None
        self.message_target = None
        # 获取当前脚本所在目录
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        # 将 schedule.json 存储在插件目录
        self.schedule_file = os.path.join(plugin_dir, 'schedule.json')
        self.load_schedule()
        asyncio.get_event_loop().create_task(self.scheduled_task()) 
        
    def load_schedule(self):
        if not self.enabled:
            logger.info("定时任务已禁用，不加载定时任务信息。")
            return
        '''加载定时任务信息'''
        if os.path.exists(self.schedule_file):
            try:
                with open(self.schedule_file, 'r') as f:
                    data = json.load(f)
                    self.user_custom_time = data.get('user_custom_time')
                    self.message_target = data.get('message_target')

                if self.user_custom_time:
                    now = datetime.datetime.now(self.user_custom_timezone)
                    target_hour, target_minute = map(int, self.user_custom_time.split(':'))
                    target_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                    if now > target_time:
                        target_time = target_time + datetime.timedelta(days=1)

                    time_until_target = (target_time - now).total_seconds()
                    logger.info(f"读取定时任务，距离下次发送摸鱼图片还剩 {int(time_until_target)} 秒")

            except Exception as e:
                logger.error(f"加载定时任务信息失败: {e}")

    def save_schedule(self):
        data = {
            'user_custom_time': self.user_custom_time,
            'message_target': self.message_target
        }
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"保存定时任务信息失败: {e}")

    async def get_moyu_image(self):
        '''获取摸鱼人日历图片'''
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.moyu_api_url) as res:
                    if res.status != 200:
                        error_text = await res.text()
                        logger.error(f"API请求失败: {res.status}, 详细原因: {error_text}")
                        return None
                    # 保存图片到临时文件
                    image_data = await res.read()
                    temp_path = os.path.join(self.temp_dir, 'moyu.jpg')
                    with open(temp_path, 'wb') as f:
                        f.write(image_data)
                    return temp_path
        except aiohttp.InvalidURL as e:
            logger.error(f"无效的URL: {self.config['moyu_api_url']}, 错误信息: {str(e)}")
        except Exception as e:
            logger.error(f"获取摸鱼图片时出错: {e.__class__.__name__}: {str(e)}")
            return None

    def parse_time(self, time: str):
        try:
            # 尝试处理 HH:MM 格式
            hour, minute = map(int, time.split(':'))
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                return None
            return f"{hour:02d}:{minute:02d}"
        except ValueError:
            try:
                # 如果用户输入的时间格式为 HHMM
                if len(time) == 4:
                    hour = int(time[:2])
                    minute = int(time[2:])
                    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                        return None
                    return f"{hour:02d}:{minute:02d}"
            except ValueError:
                return None

    @filter.command("set_time")
    async def set_time(self, event: AstrMessageEvent, time: str):
        '''设置发送摸鱼图片的时间 格式为 HH:MM或HHMM'''
        time = time.strip()
        parsed_time = self.parse_time(time)
        if not parsed_time:
            yield event.plain_result("时间格式错误，请输入正确的格式，例如：09:00或0900")
            return
        self.user_custom_time = parsed_time
        # 保存消息发送目标
        self.message_target = event.unified_msg_origin
        yield event.plain_result(f"自定义时间已设置为: {self.user_custom_time}")
        self.save_schedule()
        self.load_schedule()
        # 重置检查计数器
        self.check_count = 0
        # 重置 next_target_time，让 scheduled_task 重新计算目标时间
        self.next_target_time = None  
        self.task_executed = False

    def save_config(self):
        """
        保存配置信息到配置文件
        """
        try:
            # 获取当前脚本所在目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 构建上一级目录的config文件夹路径
            parent_dir = os.path.dirname(current_dir)
            grandparent_dir = os.path.dirname(os.path.dirname(current_dir))
            config_dir = os.path.join(grandparent_dir, 'config')
            # 确保配置目录存在
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            config_file = os.path.join(config_dir, 'astrbot_plugin_moyurenpro_config.json')
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            # 添加日志记录保存目录
            logger.info(f"配置文件已保存到: {config_file}")
        except Exception as e:
            logger.error(f"保存配置文件时出错: {e}")

    #async def terminate(self):
        """
        关闭定时任务并清理缓存
        """
        # 禁用定时任务
        #self.enabled = False
        #self.config["enabled"] = self.enabled
        #self.save_config()  # 保存配置文件
        #logger.info(f"定时任务启用状态已更新为: {self.enabled}")
        #try:
        #    self.save_schedule()
        #    logger.info("定时任务配置已保存")
        #except Exception as e:
        #    logger.error(f"保存定时任务配置时出错: {e}")
        # 清理临时目录
        #import shutil
        #if os.path.exists(self.temp_dir):
        #    shutil.rmtree(self.temp_dir)
        #    logger.info("临时目录已清理")
        #else:
        #    logger.info("临时目录不存在，无需清理")

    @filter.command("timed_tasks")
    async def toggle(self, event: AstrMessageEvent):
        """
        切换定时任务的启用/禁用状态
        """
        self.enabled = not self.enabled
        status = "启用" if self.enabled else "禁用"
        self.config["enabled"] = self.enabled
        self.save_config()  # 保存配置文件
        self.save_schedule()  # 保存更新后的配置
        yield event.plain_result(f"摸鱼人日历已{status}")        
        self.load_schedule()  # 载入初始化

    @filter.command("reset_time")
    async def reset_time(self, event: AstrMessageEvent):
        '''重置发送摸鱼图片的时间'''
        self.user_custom_time = None
        self.message_target = None
        self.save_schedule()
        yield event.plain_result("自定义时间已重置")

    @filter.command("execute_now")
    async def execute_now(self, event: AstrMessageEvent):
        '''立即发送！'''
        image_path = await self.get_moyu_image()
        if not image_path:
            yield event.plain_result("获取摸鱼图片失败，请稍后再试")
            return
        now = datetime.datetime.now(self.user_custom_timezone)
        current_time = now.strftime("%Y-%m-%d %H:%M")
        chain = [
            Plain("📅 摸鱼人日历"),
            Plain(f"🎯 {current_time}"),
            Image.fromFileSystem(image_path),  # 使用 fromFileSystem 方法
            Plain("⏰ 摸鱼提醒：工作再累，一定不要忘记摸鱼哦 ~")
        ]
        # 发送失败重试
        max_retries = 3
        for retry in range(max_retries):
            try:
                yield event.chain_result(chain)
                logger.info("摸鱼图片发送成功。")
                break
            except Exception as e:
                if retry < max_retries - 1:
                    logger.error(f"发送消息失败，第 {retry + 1} 次重试: {str(e)}")
                    await asyncio.sleep(5)  # 等待 5 秒后重试
                else:
                    logger.error(f"发送消息失败，达到最大重试次数: {str(e)}")
                    yield event.plain_result("发送消息失败，请稍后再试")

    @filter.command("set_timezone")
    async def set_timezone(self, event: AstrMessageEvent, timezone: str):
        """
        设置发送摸鱼图片的时区
        如 'Asia/Shanghai'
        """
        try:
            self.user_custom_timezone = ZoneInfo(timezone)
            self.config['default_timezone'] = timezone
            yield event.plain_result(f"时区已设置为: {timezone}")
            self.save_config()  # 添加保存配置的操作
        except ZoneInfoNotFoundError:
            yield event.plain_result("未知的时区，请输入有效的时区名称，例如：Asia/Shanghai")

    def get_next_target_time(self, now):
        """
        根据当前时间计算下一次发送摸鱼图片的目标时间。

        当前时间（datetime.datetime 对象）
        下一次发送摸鱼图片的目标时间（datetime.datetime 对象）
        """
        if not self.enabled:
            return None
        # 从用户自定义时间中提取小时和分钟
        target_hour, target_minute = map(int, self.user_custom_time.split(':'))
        # 创建目标时间对象，将当前时间的小时和分钟替换为目标小时和分钟
        target_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        # 如果当前时间已经超过目标时间，将目标时间设置为明天的同一时间
        if now > target_time:
            target_time = target_time + datetime.timedelta(days=1)
        return target_time

    async def scheduled_task(self):
        self.next_target_time = None
        # 初始化计数器
        check_count = 0
        # 添加标志位，记录任务是否已经执行
        task_executed = False
        while True:
            if not self.enabled:
                await asyncio.sleep(60)
                continue
            try:
                if not self.user_custom_time or not self.message_target:
                    check_count += 1
                    if check_count >= 3:
                        # 不退出循环，而是继续等待
                        await asyncio.sleep(60)
                        continue
                    await asyncio.sleep(60)
                    continue

                # 获取当前时间，使用用户自定义的时区
                now = datetime.datetime.now(self.user_custom_timezone)
                logger.info(f"获取当前时间: {now}")

                # 检查是否到零点，若是则重置标志位
                if now.hour == 0 and now.minute == 0:
                    task_executed = False
                    logger.info("已到零点，重置任务执行标志")

                # 检查当前日期是否为工作日
                is_workday = calendar.is_workday(now.date())
                if is_workday:
                    logger.info(f"当前日期 {now.date()} 是工作日，继续执行定时任务。")
                if not is_workday:
                    logger.info(f"当前日期 {now.date()} 不是工作日，等待到下一天午夜继续检查。")
                    # 如果不是工作日，计算到下一天午夜的时间差
                    next_day = now + datetime.timedelta(days=1)
                    next_day_midnight = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
                    time_until_next_day = (next_day_midnight - now).total_seconds()
                    logger.info(f"距离下一天午夜还有 {int(time_until_next_day)} 秒，开始等待。")
                    # 等待到下一天午夜再继续检查
                    await asyncio.sleep(time_until_next_day)
                    continue

                # 如果下一次目标时间未设置或当前时间已经超过目标时间，重新计算下一次目标时间
                if self.next_target_time is None or now > self.next_target_time:
                    self.next_target_time = self.get_next_target_time(now)
                # 计算当前时间距离下一次目标时间的秒数
                time_until_target = (self.next_target_time - now).total_seconds()
                

                # 记录日志，显示距离下一次发送摸鱼图片的剩余时间
                logger.info(f"距离下次发送摸鱼图片还剩 {time_until_target} 秒")

                # 当剩余时间大于 60 秒时，每次等待 60 秒
                while time_until_target > 60:
                    if not self.enabled:
                        logger.info("定时任务已禁用，跳出等待循环。")
                        break
                    await asyncio.sleep(60)
                    # 更新当前时间
                    now = datetime.datetime.now(self.user_custom_timezone)
                    # 检查 self.next_target_time 是否为 None
                    if self.next_target_time is None:
                        self.next_target_time = self.get_next_target_time(now)
                        if self.next_target_time is None:
                            logger.error("无法计算下一次目标时间，等待一段时间后重试。")
                            await asyncio.sleep(60)
                            continue
                    # 重新计算剩余时间
                    time_until_target = (self.next_target_time - now).total_seconds()

                # 当剩余时间小于等于 60 秒时，等待剩余时间
                if time_until_target <= 80 and self.enabled:
                    logger.info(f"等待 {time_until_target} 秒")
                    await asyncio.sleep(time_until_target)
                    # 等待结束后，再次检查是否到了执行任务的时间
                    now = datetime.datetime.now(self.user_custom_timezone)
                    if now >= self.next_target_time:
                        logger.info("已到达目标时间，准备执行任务")
                    else:
                        logger.info(f"还未到达目标时间，当前时间: {now}, 目标时间: {self.next_target_time}")

                # 检查任务是否已经执行
                if not task_executed:
                    # 获取摸鱼图片的本地路径
                    image_path = await self.get_moyu_image()
                    if image_path:
                        # 获取当前时间的字符串表示
                        current_time = now.strftime("%Y-%m-%d %H:%M")
                        # 创建消息链，包含摸鱼日历标题、当前时间、图片和摸鱼提醒
                        message_chain = MessageChain([
                            Plain("📅 摸鱼人日历"),
                            Plain(f"🎯 {current_time}"),
                            Image.fromFileSystem(image_path),  # 使用 fromFileSystem 方法
                            Plain("⏰ 摸鱼提醒：工作再累，一定不要忘记摸鱼哦 ~")
                        ])
                        # 发送失败重试机制
                        max_retries = 3
                        for retry in range(max_retries):
                            try:
                                # 发送消息链到指定的消息目标
                                await self.context.send_message(self.message_target, message_chain)
                                logger.info("摸鱼图片发送成功。")
                                # 标记任务已执行
                                task_executed = True
                                break
                            except Exception as e:
                                if retry < max_retries - 1:
                                    logger.error(f"发送消息失败，第 {retry + 1} 次重试: {str(e)}")
                                    await asyncio.sleep(5)  # 等待 5 秒后重试
                                else:
                                    logger.error(f"定时发送消息失败: {str(e)}")
                                    # 即使发送失败，也标记任务已执行
                                    task_executed = True

                # 计算下一次目标时间
                self.next_target_time = self.get_next_target_time(now)
                logger.info(f"计算下一次目标时间: {self.next_target_time}")

            except Exception as e:
                # 记录定时任务出错的错误日志
                logger.error(f"定时任务出错: {str(e)}")
                # 记录错误详情
                logger.error(f"错误详情: {e.__class__.__name__}")
                import traceback
                # 记录错误堆栈信息
                logger.error(f"堆栈信息: {traceback.format_exc()}")
                # 初始化错误重试计数器
                error_retry_count = 0
                # 设置最大重试次数
                max_retry_count = 3
                while error_retry_count < max_retry_count:
                    # 出错后等待 60 秒再重试
                    logger.info(f"定时任务出错，第 {error_retry_count + 1} 次重试，等待 60 秒")
                    await asyncio.sleep(60)
                    error_retry_count += 1
                    try:
                        # 尝试重新执行任务逻辑
                        if not self.user_custom_time or not self.message_target:
                            check_count += 1
                            if check_count >= 3:
                                logger.error("检查设置次数达到上限，暂停检查，等待设置更新。")
                                continue
                            continue
                        break  # 如果成功执行，跳出重试循环
                    except Exception as e:
                        logger.error(f"第 {error_retry_count} 次重试失败: {str(e)}")
                if error_retry_count == max_retry_count:
                    logger.error("达到最大重试次数，暂停任务，等待设置更新。")
         

