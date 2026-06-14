import json
import os
import datetime
from jinja2 import Template

def generate_report():
    # 数据文件路径
    data_dir = os.path.join(os.getcwd(), "data")
    grades_file = os.path.join(data_dir, "student_grades.json")
    
    if not os.path.exists(grades_file):
        print(f"Error: {grades_file} not found.")
        return

    with open(grades_file, 'r', encoding='utf-8') as f:
        all_grades = json.load(f)

    target_grades = []
    for sid, data in all_grades.items():
        data['id'] = sid
        target_grades.append(data)

    # 计算统计数据
    subjects = ['math', 'english', 'science']
    stats = {}
    for subj in subjects:
        scores = [s.get(subj, 0) for s in target_grades]
        if scores:
            stats[subj] = {
                "average": sum(scores) / len(scores),
                "max": max(scores),
                "min": min(scores)
            }

    # 生成HTML
    html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>成绩统计报告</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: center; }
        th { background-color: #f2f2f2; }
        h1, h2 { color: #333; }
        .stats { background-color: #f9f9f9; padding: 10px; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>成绩统计报告</h1>
    <p>生成时间: {{ generate_time }}</p>
    
    <h2>学生成绩详情</h2>
    <table>
        <thead>
            <tr>
                <th>学号</th>
                <th>姓名</th>
                <th>数学</th>
                <th>英语</th>
                <th>科学</th>
            </tr>
        </thead>
        <tbody>
            {% for student in students %}
            <tr>
                <td>{{ student.id }}</td>
                <td>{{ student.name }}</td>
                <td>{{ student.math }}</td>
                <td>{{ student.english }}</td>
                <td>{{ student.science }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <h2>统计概览</h2>
    <div class="stats">
        <table>
            <thead>
                <tr>
                    <th>科目</th>
                    <th>平均分</th>
                    <th>最高分</th>
                    <th>最低分</th>
                </tr>
            </thead>
            <tbody>
                {% for subj, data in stats.items() %}
                <tr>
                    <td>{{ subj }}</td>
                    <td>{{ "%.2f"|format(data.average) }}</td>
                    <td>{{ data.max }}</td>
                    <td>{{ data.min }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    template = Template(html_template)
    html_content = template.render(
        students=target_grades,
        stats=stats,
        generate_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # 保存HTML文件
    report_filename = "grade_report.html"
    report_path = os.path.join(data_dir, report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Report generated at {report_path}")

if __name__ == "__main__":
    generate_report()
