#!/usr/bin/env python3
"""
自动校验blog_post.md的硬指标：
1. 文件是否存在
2. 格式是否为有效的Markdown
3. 字数是否在400-600字范围内
4. 是否包含标题
5. 段落数量是否符合要求
6. 是否包含至少3个二级标题
7. 是否有结尾总结
"""
import os
import re
from pathlib import Path
import markdown

def count_words(text):
    """统计中文和英文单词数"""
    # 移除Markdown标记
    clean_text = re.sub(r'#.*\n', '', text)  # 移除标题
    clean_text = re.sub(r'\*.*\*', '', clean_text)  # 移除粗体斜体
    clean_text = re.sub(r'\[.*\]\(.*\)', '', clean_text)  # 移除链接
    clean_text = re.sub(r'!\[.*\]\(.*\)', '', clean_text)  # 移除图片
    clean_text = re.sub(r'`.*`', '', clean_text)  # 移除代码
    
    # 统计中文
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', clean_text))
    # 统计英文单词
    english_words = len(re.findall(r'[a-zA-Z]+', clean_text))
    
    return chinese_chars + english_words

def validate_blog_post(file_path):
    """校验博客文章，返回得分和详情"""
    score = 0.0
    max_score = 10.0
    details = []
    
    # 1. 检查文件是否存在（2分）
    if not os.path.exists(file_path):
        details.append("❌ 文件不存在")
        return 0.0, details
    score += 2.0
    details.append("✅ 文件存在")
    
    # 读取文件内容
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        details.append(f"❌ 文件读取失败: {e}")
        return 0.0, details
    
    # 2. 检查是否有标题（1分）
    if re.match(r'^# .+', content.strip()):
        score += 1.0
        details.append("✅ 包含一级标题")
    else:
        details.append("❌ 缺少一级标题")
    
    # 3. 检查二级标题数量（2分，至少3个）
    h2_count = len(re.findall(r'^## .+', content, re.MULTILINE))
    if h2_count >= 3:
        score += 2.0
        details.append(f"✅ 二级标题数量符合要求: {h2_count}个")
    else:
        details.append(f"❌ 二级标题数量不足: {h2_count}个，需要至少3个")
    
    # 4. 检查字数（2分，400-600字）
    word_count = count_words(content)
    if 400 <= word_count <= 600:
        score += 2.0
        details.append(f"✅ 字数符合要求: {word_count}字")
    else:
        details.append(f"❌ 字数不符合要求: {word_count}字，需要400-600字")
        # 部分得分
        if 300 <= word_count <= 700:
            score += 1.0
    
    # 5. 检查段落结构（1分，至少5个段落）
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    if len(paragraphs) >= 5:
        score += 1.0
        details.append(f"✅ 段落数量符合要求: {len(paragraphs)}段")
    else:
        details.append(f"❌ 段落数量不足: {len(paragraphs)}段，需要至少5段")
    
    # 6. 检查是否有总结部分（1分）
    if re.search(r'##.*(总结|结论|Conclusion|Summary)', content, re.IGNORECASE):
        score += 1.0
        details.append("✅ 包含总结/结论部分")
    else:
        details.append("❌ 缺少总结/结论部分")
    
    # 7. 检查Markdown格式有效性（1分）
    try:
        html = markdown.markdown(content)
        if html.strip():
            score += 1.0
            details.append("✅ Markdown格式有效")
        else:
            details.append("❌ Markdown格式无效")
    except:
        details.append("❌ Markdown格式解析失败")
    
    # 转换为10分制
    final_score = round(score, 2)
    details.append(f"\n📊 总分: {final_score}/10.0")
    
    return final_score, details

def main():
    # 可能的文件路径
    possible_paths = [
        "/app/blog_post.md",
        "/workspace/blog_post.md",
        "/blog_post.md"
    ]
    
    file_path = None
    for path in possible_paths:
        if os.path.exists(path):
            file_path = path
            break
    
    if not file_path:
        print("0.0")
        with open("/logs/verifier/autograder_details.txt", 'w') as f:
            f.write("❌ 未找到blog_post.md文件\n")
        return
    
    score, details = validate_blog_post(file_path)
    
    # 保存详情
    with open("/logs/verifier/autograder_details.txt", 'w') as f:
        f.write("自动校验结果:\n")
        f.write("=" * 30 + "\n")
        for detail in details:
            f.write(f"{detail}\n")
    
    # 输出得分（转换为0-1分制）
    normalized_score = round(score / 10.0, 2)
    print(normalized_score)

if __name__ == "__main__":
    main()