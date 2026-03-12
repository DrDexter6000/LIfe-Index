#!/bin/bash
# Life Index OpenClaw 定时任务配置脚本
# 版本: 基于OpenClaw 2026.3.8 官方文档
# 适用: Ubuntu + OpenClaw 2026.3.8+
# 状态: 已验证基础功能，可直接使用

# ============================================
# 配置说明
# ============================================
# 
# 使用前请确认:
# 1. OpenClaw版本: 2026.3.8 (已确认)
# 2. Life Index安装路径: 请替换 [LIFE_INDEX_PATH]
# 3. 时区: 默认 Asia/Shanghai (可修改)
#
# 执行方式:
#   chmod +x openclaw-cron-config-final.sh
#   ./openclaw-cron-config-final.sh
#
# 或者逐行复制命令执行

# ============================================
# 变量配置 (请修改此处)
# ============================================

# Life Index技能路径 - 请替换为实际路径
# 示例: /home/username/openclaw/skills/life-index
# 示例: /app/skills/life-index
LIFE_INDEX_PATH="[请替换为实际路径]"

# 时区设置
TIMEZONE="Asia/Shanghai"

# ============================================
# 颜色输出
# ============================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ============================================
# 预检查
# ============================================

echo -e "${YELLOW}Life Index 定时任务配置脚本${NC}"
echo "============================================"
echo ""

# 检查OpenClaw是否安装
if ! command -v openclaw &> /dev/null; then
    echo -e "${RED}错误: 未找到openclaw命令${NC}"
    echo "请确认OpenClaw已正确安装"
    exit 1
fi

# 检查版本
OPENCLAW_VERSION=$(openclaw --version 2>&1 | head -1)
echo -e "${GREEN}✓ OpenClaw版本: $OPENCLAW_VERSION${NC}"

# 检查路径是否已配置
if [ "$LIFE_INDEX_PATH" = "[请替换为实际路径]" ]; then
    echo -e "${RED}错误: 请修改脚本中的 LIFE_INDEX_PATH 变量${NC}"
    echo "当前值: $LIFE_INDEX_PATH"
    echo ""
    echo "请编辑此脚本，将 LIFE_INDEX_PATH 设置为Life Index的实际安装路径"
    exit 1
fi

# 检查目录是否存在
if [ ! -d "$LIFE_INDEX_PATH" ]; then
    echo -e "${RED}错误: 目录不存在: $LIFE_INDEX_PATH${NC}"
    echo "请确认路径正确"
    exit 1
fi

# 检查工具是否存在
if [ ! -f "$LIFE_INDEX_PATH/tools/search_journals.py" ]; then
    echo -e "${RED}错误: 未找到Life Index工具${NC}"
    echo "路径: $LIFE_INDEX_PATH/tools/search_journals.py"
    exit 1
fi

echo -e "${GREEN}✓ Life Index路径: $LIFE_INDEX_PATH${NC}"
echo -e "${GREEN}✓ 工具可访问性: 已验证${NC}"
echo ""

# ============================================
# 函数: 创建定时任务
# ============================================

create_daily_report_job() {
    echo -e "${YELLOW}创建日报任务...${NC}"
    
    openclaw cron add \
        --name "life-index-daily-report" \
        --cron "0 22 * * *" \
        --tz "$TIMEZONE" \
        --session isolated \
        --message "执行Life Index日报生成任务。

步骤：
1. 进入Life Index目录: cd $LIFE_INDEX_PATH
2. 获取今天日期: TODAY=\$(date +%Y-%m-%d)
3. 查询今日日志: python tools/search_journals.py --date \$TODAY --limit 100
4. 分析结果:
   - 如果有日志: 生成日报并推送给用户
   - 如果无日志: 告知用户今日无记录

日报格式：
【Life Index 日报】\$TODAY

📝 今日概要
[用2-3句话总结今日核心内容]

⚡ 要点速览
• [要点1，简洁明了]
• [要点2]
• [要点3]

💡 AI建议
→ [建议1，祈使语气]
→ [建议2]

🔔 要事提醒
[待跟进事项，或'无待跟进事项']" \
        --announce \
        --timeout 120
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 日报任务创建成功${NC}"
    else
        echo -e "${RED}✗ 日报任务创建失败${NC}"
        return 1
    fi
}

create_weekly_report_job() {
    echo -e "${YELLOW}创建周报任务...${NC}"
    
    openclaw cron add \
        --name "life-index-weekly-report" \
        --cron "10 22 * * 0" \
        --tz "$TIMEZONE" \
        --session isolated \
        --message "执行Life Index周报生成任务。

步骤：
1. 进入Life Index目录: cd $LIFE_INDEX_PATH
2. 计算本周日期范围（周一到周日）
3. 查询本周日志: python tools/search_journals.py --date-from [周一] --date-to [周日] --limit 500
4. 生成周报并推送给用户

周报格式：
【Life Index 周报】[日期范围]

📊 本周概览
本周共记录N篇日志，主题分布: [work: X篇, life: Y篇, ...]

🎯 核心主题
[2-3个核心主题]

⚡ 高光时刻
• [重要记录1]
• [重要记录2]

📈 趋势观察
[AI对用户本周的观察和建议]" \
        --announce \
        --timeout 180
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 周报任务创建成功${NC}"
    else
        echo -e "${RED}✗ 周报任务创建失败${NC}"
        return 1
    fi
}

create_monthly_report_job() {
    echo -e "${YELLOW}创建月报任务...${NC}"
    
    openclaw cron add \
        --name "life-index-monthly-report" \
        --cron "30 18 28-31 * *" \
        --tz "$TIMEZONE" \
        --session isolated \
        --message "执行Life Index月报生成任务。

步骤：
1. 检查今天是否是本月最后一天，如果不是则跳过
2. 进入Life Index目录: cd $LIFE_INDEX_PATH
3. 生成本月摘要: python tools/generate_abstract.py --month \$(date +%Y-%m)
4. 读取摘要文件: Journals/YYYY/MM/monthly_report_YYYY-MM.md
5. 生成月报推送给用户，并告知文件位置

月报格式：
【Life Index 月报】YYYY年MM月

📊 数据概览
本月共记录N篇日志

📝 月度精选
[3-5篇重要日志标题]

🎯 核心洞察
[基于数据的AI洞察]

💡 下月建议
→ [建议1]
→ [建议2]

📄 详细报告已保存至
Journals/YYYY/MM/monthly_report_YYYY-MM.md" \
        --announce \
        --timeout 300
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 月报任务创建成功${NC}"
    else
        echo -e "${RED}✗ 月报任务创建失败${NC}"
        return 1
    fi
}

create_index_maintenance_job() {
    echo -e "${YELLOW}创建索引维护任务...${NC}"
    
    openclaw cron add \
        --name "life-index-index-maintenance" \
        --cron "50 23 * * *" \
        --tz "$TIMEZONE" \
        --session isolated \
        --message "执行Life Index索引维护任务。

步骤：
1. 进入Life Index目录: cd $LIFE_INDEX_PATH
2. 更新FTS索引: python tools/build_index.py
3. 尝试更新向量索引: python tools/build_index.py --semantic 2>/dev/null || echo '向量索引跳过'
4. 记录执行结果

约束：
- 此任务静默执行，无需通知用户
- 如果失败，记录错误，下次执行重试
- 不向用户推送结果" \
        --timeout 600
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 索引维护任务创建成功${NC}"
    else
        echo -e "${RED}✗ 索引维护任务创建失败${NC}"
        return 1
    fi
}

# ============================================
# 主菜单
# ============================================

show_menu() {
    echo "============================================"
    echo "请选择要创建的任务:"
    echo "============================================"
    echo "1) 创建全部4个任务 (日报+周报+月报+索引)"
    echo "2) 仅创建日报任务"
    echo "3) 仅创建周报任务"
    echo "4) 仅创建月报任务"
    echo "5) 仅创建索引维护任务"
    echo "6) 查看当前定时任务列表"
    echo "7) 删除所有Life Index定时任务"
    echo "0) 退出"
    echo "============================================"
    read -p "请输入选项 [0-7]: " choice
}

# ============================================
# 主程序
# ============================================

while true; do
    show_menu
    
    case $choice in
        1)
            echo ""
            echo "开始创建全部定时任务..."
            create_daily_report_job
            create_weekly_report_job
            create_monthly_report_job
            create_index_maintenance_job
            echo ""
            echo -e "${GREEN}全部任务创建完成！${NC}"
            echo "使用 'openclaw cron list' 查看任务列表"
            ;;
        2)
            echo ""
            create_daily_report_job
            ;;
        3)
            echo ""
            create_weekly_report_job
            ;;
        4)
            echo ""
            create_monthly_report_job
            ;;
        5)
            echo ""
            create_index_maintenance_job
            ;;
        6)
            echo ""
            echo -e "${YELLOW}当前定时任务列表:${NC}"
            openclaw cron list
            ;;
        7)
            echo ""
            echo -e "${RED}警告: 这将删除所有Life Index定时任务${NC}"
            read -p "确认删除? [y/N]: " confirm
            if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                openclaw cron rm life-index-daily-report 2>/dev/null
                openclaw cron rm life-index-weekly-report 2>/dev/null
                openclaw cron rm life-index-monthly-report 2>/dev/null
                openclaw cron rm life-index-index-maintenance 2>/dev/null
                echo -e "${GREEN}已删除所有Life Index定时任务${NC}"
            else
                echo "已取消"
            fi
            ;;
        0)
            echo ""
            echo "退出脚本"
            exit 0
            ;;
        *)
            echo ""
            echo -e "${RED}无效选项${NC}"
            ;;
    esac
    
    echo ""
    read -p "按回车键继续..."
    echo ""
done
