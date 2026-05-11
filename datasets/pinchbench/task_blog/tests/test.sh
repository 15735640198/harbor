#!/bin/bash
set -euo pipefail

GRADING_TYPE=$(grep 'grading_type' /task.toml | cut -d'"' -f2)
echo "Running grading for task: task_blog"
echo "Grading type: $GRADING_TYPE"

# Create logs directory
mkdir -p /logs/verifier
mkdir -p /logs/verifier/agent_output

# === 新增：收集智能体生成的所有文件 ===
echo "Collecting agent output files from workspace and app directories..."

# 创建输出目录
mkdir -p /logs/verifier/agent_output/workspace
mkdir -p /logs/verifier/agent_output/app

# 收集/workspace目录
if [ -d "/workspace" ]; then
    echo "=== Full workspace directory structure ===" > /logs/verifier/workspace_structure.txt
    find /workspace -type f >> /logs/verifier/workspace_structure.txt
    
    cp -r /workspace/* /logs/verifier/agent_output/workspace/ || echo "Warning: Failed to copy some files from workspace"
    
    echo "Workspace files:" > /logs/verifier/agent_output/file_list.txt
    ls -la /workspace >> /logs/verifier/agent_output/file_list.txt
fi

# 收集/app目录（这才是openclaw的真实工作目录！）
if [ -d "/app" ]; then
    echo -e "\n=== Full app directory structure ===" >> /logs/verifier/workspace_structure.txt
    find /app -type f >> /logs/verifier/workspace_structure.txt
    
    cp -r /app/* /logs/verifier/agent_output/app/ 2>/dev/null || echo "Warning: Failed to copy some files from app"
    
    echo -e "\nApp directory files:" >> /logs/verifier/agent_output/file_list.txt
    ls -la /app >> /logs/verifier/agent_output/file_list.txt
    
    # 专门检查blog_post.md
    if [ -f "/app/blog_post.md" ]; then
        echo "✅ SUCCESS: blog_post.md found in /app directory!" >> /logs/verifier/debug.log
        cp /app/blog_post.md /logs/verifier/
        # 同时复制到更明显的位置
        cp /app/blog_post.md /logs/verifier/agent_output/
    else
        echo "❌ FAIL: blog_post.md not found in /app directory" >> /logs/verifier/debug.log
        # 搜索整个容器
        find / -name "blog_post.md" 2>/dev/null >> /logs/verifier/debug.log || echo "blog_post.md not found anywhere" >> /logs/verifier/debug.log
    fi
else
    echo "❌ FAIL: /app directory does not exist" >> /logs/verifier/debug.log
fi
# ===================================

# Test python availability
echo "Testing Python availability..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    echo "Python not found in the image, setting default score to 0"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi
echo "Using Python command: $PYTHON_CMD"

# Initialize scores
AUTOMATED_SCORE=0.0

# 自动校验评分（替代LLM judge）
echo "Running automated grading..."
if $PYTHON_CMD /tests/autograder.py > /tmp/score.txt; then
    AUTOMATED_SCORE=$(cat /tmp/score.txt)
    echo "Automated grading score: $AUTOMATED_SCORE"
else
    echo "Automated grading failed, using default score 0"
    AUTOMATED_SCORE=0.0
fi

# Calculate final reward
FINAL_SCORE=$AUTOMATED_SCORE

echo "Final score: $FINAL_SCORE"
echo $FINAL_SCORE > /logs/verifier/reward.txt

# Write grading details
cat > /logs/verifier/grading_details.json << EOF
{
    "task_id": "task_blog",
    "grading_type": "automated",
    "automated_score": $AUTOMATED_SCORE,
    "final_score": $FINAL_SCORE,
    "timestamp": "$(date -Iseconds)"
}
EOF

echo "Grading completed successfully"
echo "Agent output files have been saved to the job directory"
