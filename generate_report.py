import os
import openpyxl
from collections import Counter
from datetime import datetime
import json

# 配置路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data", "vision_records", "student_records.xlsx")
REPORT_FILE = os.path.join(BASE_DIR, "data", "vision_records", "analysis_report.html")

def generate_html_report():
    if not os.path.exists(DATA_FILE):
        print(f"Error: 数据文件不存在: {DATA_FILE}")
        return

    print(f"正在读取数据: {DATA_FILE}...")
    try:
        wb = openpyxl.load_workbook(DATA_FILE)
        ws = wb.active
        
        # 提取数据 (假设表头在第一行: 时间, 学号, 设备ID, 回复内容, 图片路径, JSON路径)
        rows = list(ws.iter_rows(min_row=2, values_only=True))
    except Exception as e:
        print(f"读取Excel失败: {e}")
        return

    total_count = len(rows)
    print(f"共找到 {total_count} 条记录")

    if total_count == 0:
        print("暂无数据可分析")
        return

    # --- 数据处理 ---
    student_counter = Counter()
    device_counter = Counter()
    date_counter = Counter()
    hour_counter = Counter()

    records = []

    for row in rows:
        # row: (time_str, student_id, device_id, content, img_path, json_path)
        if not row or len(row) < 3:
            continue
            
        time_str, student_id, device_id = row[0], row[1], row[2]
        
        # 统计学号
        student_id_str = str(student_id).strip() if student_id else "未知"
        student_counter[student_id_str] += 1
        
        # 统计设备
        device_counter[str(device_id)] += 1
        
        # 解析时间
        try:
            # 兼容可能的不同时间格式，当前代码生成的是 "%Y-%m-%d %H:%M:%S"
            dt = datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
            hour_str = dt.strftime("%H:00")
            
            date_counter[date_str] += 1
            hour_counter[hour_str] += 1
            
            records.append({
                "time": str(time_str),
                "student": student_id_str,
                "device": str(device_id),
                "content": str(row[3])[:50] + "..." if row[3] else ""
            })
        except Exception:
            pass

    # 排序数据以便绘图
    # 1. 学号活跃度
    sorted_students = student_counter.most_common(10)
    student_labels = [k for k, v in sorted_students]
    student_data = [v for k, v in sorted_students]

    # 2. 每日趋势
    sorted_dates = sorted(date_counter.items())
    date_labels = [k for k, v in sorted_dates]
    date_data = [v for k, v in sorted_dates]

    # 3. 时段分布 (00:00 - 23:00)
    hours = [f"{h:02d}:00" for h in range(24)]
    hour_data = [hour_counter[h] for h in hours]

    # --- 生成 HTML ---
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>小智学号拍照数据分析报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ text-align: center; color: #333; }}
        .summary {{ display: flex; justify-content: space-around; margin-bottom: 30px; padding: 20px; background: #e3f2fd; border-radius: 8px; }}
        .stat-box {{ text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #1976d2; }}
        .stat-label {{ color: #666; }}
        .chart-row {{ display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 30px; }}
        .chart-container {{ flex: 1; min-width: 400px; background: white; padding: 15px; border-radius: 8px; border: 1px solid #eee; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f8f9fa; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📸 小智拍照作业提交分析报告</h1>
        <p style="text-align: center; color: #666;">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

        <div class="summary">
            <div class="stat-box">
                <div class="stat-value">{total_count}</div>
                <div class="stat-label">总提交次数</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{len(student_counter)}</div>
                <div class="stat-label">活跃学生数</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{len(device_counter)}</div>
                <div class="stat-label">活跃设备数</div>
            </div>
        </div>

        <div class="chart-row">
            <div class="chart-container">
                <h3 style="text-align:center">🏆 学生活跃度 TOP 10</h3>
                <canvas id="studentChart"></canvas>
            </div>
            <div class="chart-container">
                <h3 style="text-align:center">📅 每日提交趋势</h3>
                <canvas id="dateChart"></canvas>
            </div>
        </div>

        <div class="chart-row">
            <div class="chart-container">
                <h3 style="text-align:center">⏰ 提交时间段分布</h3>
                <canvas id="hourChart"></canvas>
            </div>
        </div>

        <h3>📝 最新提交记录 (最近10条)</h3>
        <table>
            <thead>
                <tr>
                    <th>时间</th>
                    <th>学号</th>
                    <th>设备ID</th>
                    <th>识别内容摘要</th>
                </tr>
            </thead>
            <tbody>
                {"".join(f"<tr><td>{r['time']}</td><td>{r['student']}</td><td>{r['device']}</td><td>{r['content']}</td></tr>" for r in reversed(records[-10:]))}
            </tbody>
        </table>
    </div>

    <script>
        // Chart 1: Student Activity
        new Chart(document.getElementById('studentChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(student_labels)},
                datasets: [{{
                    label: '提交次数',
                    data: {json.dumps(student_data)},
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{ scales: {{ y: {{ beginAtZero: true }} }} }}
        }});

        // Chart 2: Date Trend
        new Chart(document.getElementById('dateChart'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(date_labels)},
                datasets: [{{
                    label: '每日提交量',
                    data: {json.dumps(date_data)},
                    fill: true,
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    tension: 0.1
                }}]
            }},
            options: {{ scales: {{ y: {{ beginAtZero: true }} }} }}
        }});

        // Chart 3: Hour Distribution
        new Chart(document.getElementById('hourChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(hours)},
                datasets: [{{
                    label: '各时段提交量',
                    data: {json.dumps(hour_data)},
                    backgroundColor: 'rgba(255, 159, 64, 0.6)',
                    borderColor: 'rgba(255, 159, 64, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{ scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
    </script>
</body>
</html>
    """

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ 报告已生成: {REPORT_FILE}")

if __name__ == "__main__":
    generate_html_report()
