import json
import os
from jinja2 import Template
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()

GENERATE_GRADE_REPORT_DESC = {
    "type": "function",
    "function": {
        "name": "generate_grade_report",
        "description": "根据学号数据生成成绩统计报告，生成HTML格式的报告。",
        "parameters": {
            "type": "object",
            "properties": {
                "student_ids": {
                    "type": "string",
                    "description": "学号列表，用逗号分隔。如果不提供，则使用所有已知学号。",
                }
            },
            "required": [],
        },
    },
}

@register_function(
    name="generate_grade_report",
    desc=GENERATE_GRADE_REPORT_DESC,
    type=ToolType.WAIT
)
def generate_grade_report(student_ids=None):
    """
    生成成绩统计报告
    """
    try:
        # 数据文件路径
        data_dir = os.path.join(os.getcwd(), "data")
        grades_file = os.path.join(data_dir, "student_grades.json")
        
        if not os.path.exists(grades_file):
            return ActionResponse(Action.REQLLM, "未找到成绩数据文件。")

        with open(grades_file, 'r', encoding='utf-8') as f:
            all_grades = json.load(f)

        target_grades = []
        if student_ids:
            ids = [s.strip() for s in student_ids.split(',')]
            for sid in ids:
                if sid in all_grades:
                    student_data = all_grades[sid]
                    student_data['id'] = sid
                    target_grades.append(student_data)
        else:
            for sid, data in all_grades.items():
                data['id'] = sid
                target_grades.append(data)

        if not target_grades:
            return ActionResponse(Action.REQLLM, "未找到指定学号的成绩数据。")

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
        import datetime
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

        # 返回访问链接
        # 假设服务器IP和端口，这里返回相对路径或者提示用户访问
        # 根据 http_server.py，/static/ 映射到 data/
        # 所以访问路径应该是 /static/grade_report.html
        
        return ActionResponse(Action.REQLLM, f"成绩报告已生成。请访问: /static/{report_filename}")

    except Exception as e:
        logger.error(f"生成成绩报告失败: {e}")
        return ActionResponse(Action.REQLLM, f"生成成绩报告失败: {e}")
