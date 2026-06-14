import os
import openpyxl
from collections import Counter
from datetime import datetime
import io
import base64
import matplotlib.pyplot as plt
import matplotlib
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from core.handle.imageHandle import send_image_to_device
import asyncio

TAG = __name__
logger = setup_logging()

# 设置支持中文的字体，尽量不依赖系统特定字体，或者随Docker分发一个字体
# 在基础镜像中不一定有中文字体，所以这里尝试设置通用sans-serif，并建议用户安装字体
# 为了简单起见，我们也可以尝试使用英文标签，或者假设Docker里有SimHei
# 这里做一个安全的配置，如果没有中文字体，可能显示方框
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False

show_homework_stats_desc = {
    "type": "function",
    "function": {
        "name": "show_homework_stats",
        "description": "当用户想要查看作业统计、学号排名或每日提交情况的图表报告时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户的具体查询意图，例如'统计报告'、'排名'等",
                }
            },
            "required": [],
        },
    },
}

DATA_FILE = "data/vision_records/student_records.xlsx"

@register_function("show_homework_stats", show_homework_stats_desc, ToolType.IOT_CTL)
def show_homework_stats(conn, query=None):
    logger.bind(tag=TAG).info(f"Generating homework stats image for device...")
    
    if not os.path.exists(DATA_FILE):
        return ActionResponse(Action.RESPONSE, result="error", response="暂无作业数据，无法生成报告。")

    try:
        # 在线程中执行绘图，避免阻塞主循环
        loop = asyncio.get_running_loop() if conn and hasattr(conn, "loop") else asyncio.new_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            _generate_and_send(conn), loop
        )
        # 等待绘图发送完成 (简单等待结果)
        # 注意：ActionResponse需要在主线程返回，但绘图和发送是异步/耗时的
        # 这里我们尽量让_generate_and_send去处理发送，这里直接返回"正在生成"的回复
        # 或者block等待结果
        result = future.result(timeout=10) # 10秒超时
        
        if result:
            return ActionResponse(Action.RESPONSE, result="success", response="统计报告已发送到您的屏幕。")
        else:
             return ActionResponse(Action.RESPONSE, result="error", response="生成报告失败。")
             
    except Exception as e:
        logger.bind(tag=TAG).error(f"Stat generation failed: {e}")
        return ActionResponse(Action.RESPONSE, result="error", response="生成报告时发生错误。")

async def _generate_and_send(conn):
    try:
        # --- 1. 读取数据 ---
        wb = openpyxl.load_workbook(DATA_FILE)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        
        if not rows:
            return False

        student_counter = Counter()
        date_counter = Counter()

        for row in rows:
            if not row or len(row) < 2: continue
            time_str = str(row[0])
            student_id = str(row[1]).strip() if row[1] else "Unknown"
            
            student_counter[student_id] += 1
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%m-%d")
                date_counter[date_str] += 1
            except:
                pass

        # --- 2. 绘图 (Matplotlib) ---
        # 创建画布：宽1000px, 高600px 左右
        # ESP32 屏幕较小，字体要大
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
        fig.suptitle('作业提交统计 / Homework Statistics', fontsize=16)

        # 图1：学号排名
        top_students = student_counter.most_common(5)
        if top_students:
            s_labels, s_vals = zip(*top_students)
            ax1.bar(s_labels, s_vals, color='skyblue')
            ax1.set_title('Top 5 Most Active Students')
            ax1.set_xlabel('Student ID')
            ax1.set_ylabel('Count')
        else:
            ax1.text(0.5, 0.5, "No Data", ha='center')

        # 图2：日期趋势
        sorted_dates = sorted(date_counter.items())
        if sorted_dates:
            d_labels, d_vals = zip(*sorted_dates)
            ax2.plot(d_labels, d_vals, marker='o', linestyle='-', color='orange')
            ax2.set_title('Daily Submission Trend')
            ax2.set_xlabel('Date')
            ax2.tick_params(axis='x', rotation=45)
        else:
            ax2.text(0.5, 0.5, "No Data", ha='center')

        plt.tight_layout()

        # --- 3. 保存到内存 ---
        buf = io.BytesIO()
        plt.savefig(buf, format='jpg', dpi=100)
        plt.close(fig)
        buf.seek(0)
        
        img_bytes = buf.getvalue()
        base64_str = base64.b64encode(img_bytes).decode('utf-8')
        
        # --- 4. 发送给设备 ---
        # 调用 imageHandle 发送
        await send_image_to_device(conn, base64_str, description="Homework Report")
        return True

    except Exception as e:
        logger.bind(tag=TAG).error(f"Error in _generate_and_send: {e}")
        return False
