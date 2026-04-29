"""LLM服务模块 - 阿里云百炼API（智能文档分析+精准填入）"""
import os
import re
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("llm_service")

# 初始化客户端
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
)

MODEL = os.getenv("LLM_MODEL", "qwen-max")


def extract_text_content(xml_content: str) -> str:
    """从XML中提取纯文本"""
    pattern = r'<w:t[^>]*>([^<]*)</w:t>'
    matches = re.findall(pattern, xml_content)
    return ' '.join(matches)


def analyze_document(xml_content: str, knowledge_base: list[dict]) -> list[dict]:
    """
    让LLM分析文档，返回需要填入的位置和内容
    """
    text_content = extract_text_content(xml_content)
    
    kb_text = "\n".join([
        f"- {item['field_name']}: {item['content']}"
        for item in knowledge_base
    ])
    
    prompt = f"""分析以下企业信息采集表，找出需要填入知识库数据的位置。

## 知识库数据
{kb_text}

## 文档文本内容
{text_content}

## 文档结构特点
1. **简单标签-值对**：如"企业名称"后面有空白单元格需要填入公司名
2. **复选框**：如"□ISO9000"，需要勾选
3. **交叉表格**：如知识产权情况表
   - 列标题：发明专利、实用新型专利、外观设计专利、软件著作权、标准、注册商标
   - 行标题：已有证书（数量）、受理中（注明申请时间）、计划申请
   - 如果知识库有"发明专利数量"的数据，应该填在"发明专利"列和"已有证书（数量）"行的交叉位置

## 任务
1. 识别文档中的标签字段
2. 智能匹配知识库数据
3. 返回填入位置（使用文档中实际存在的标签文本）

## 输出格式（严格JSON数组）
[
  {{"type": "fill", "label": "文档中存在的标签文本", "value": "要填入的值"}},
  {{"type": "fill_after_row", "row_label": "行标签", "after_col": "列标签", "value": "值"}},
  {{"type": "check", "label": "要勾选的复选框名称"}}
]

重要规则：
- label必须是文档中实际存在的完整文本
- 对于交叉表格，使用fill_after_row类型，指定行标签和在哪个列标签之后
- 对于简单填充，使用fill类型
- 只返回知识库中有对应数据的项
- 如果没有匹配项，返回空数组 []

只返回JSON数组。"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "你是一个JSON生成器，只返回有效的JSON格式数据。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        result = response.choices[0].message.content.strip()
        logger.info(f"LLM分析结果: {result}")
        
        if result.startswith("```json"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
        
        mappings = json.loads(result)
        
        valid_mappings = []
        for m in mappings:
            if isinstance(m, dict):
                m.setdefault("type", "fill")
                valid_mappings.append(m)
                if m.get("type") == "fill_after_row":
                    logger.info(f"  映射: [交叉] {m.get('row_label')} x {m.get('after_col')} -> {m.get('value')}")
                elif m.get("type") == "check":
                    logger.info(f"  映射: [勾选] {m.get('label')}")
                else:
                    logger.info(f"  映射: [填充] {m.get('label')} -> {m.get('value')}")
        
        return valid_mappings
        
    except Exception as e:
        logger.error(f"LLM分析失败: {e}")
        return []


def find_and_fill_after_label(xml_content: str, label: str, value: str) -> tuple[str, bool]:
    """在指定标签后的空白单元格中填入值"""
    label_escaped = re.escape(label)
    label_match = re.search(f'>{label_escaped}</w:t>', xml_content)
    if not label_match:
        logger.warning(f"  未找到标签: {label}")
        return xml_content, False
    
    label_end = label_match.end()
    search_region = xml_content[label_end:label_end+3000]
    
    # 策略1：查找空白段落
    empty_para_pattern = r'(<w:p>(?:(?!<w:r>).)*?<w:pPr>.*?</w:pPr>)(</w:p>)'
    match = re.search(empty_para_pattern, search_region, re.DOTALL)
    if match:
        insert_pos = label_end + match.end(1)
        insert_text = f'<w:r><w:t>{value}</w:t></w:r>'
        new_xml = xml_content[:insert_pos] + insert_text + xml_content[insert_pos:]
        logger.info(f"  ✓ 在 '{label}' 后填入 '{value}'")
        return new_xml, True
    
    # 策略2：简单模式
    simple_pattern = r'(</w:pPr>)(</w:p></w:tc>)'
    match = re.search(simple_pattern, search_region)
    if match:
        insert_pos = label_end + match.end(1)
        insert_text = f'<w:r><w:t>{value}</w:t></w:r>'
        new_xml = xml_content[:insert_pos] + insert_text + xml_content[insert_pos:]
        logger.info(f"  ✓ 在 '{label}' 后填入 '{value}'（策略2）")
        return new_xml, True
    
    logger.warning(f"  未找到 '{label}' 后的空白单元格")
    return xml_content, False


def find_and_fill_cross_table(xml_content: str, row_label: str, col_label: str, value: str) -> tuple[str, bool]:
    """
    在交叉表格中填入值
    1. 先找到表头行，确定col_label是第几列
    2. 再找到row_label所在的行
    3. 在该行的对应列单元格中填入值
    """
    # 第一步：找到列标签在表头行中的位置（第几列）
    col_match = re.search(f'>{re.escape(col_label)}</w:t>', xml_content)
    if not col_match:
        logger.warning(f"  未找到列标签: {col_label}")
        return xml_content, False
    
    # 找到表头行
    header_row_start = xml_content.rfind('<w:tr', 0, col_match.start())
    header_row_end = xml_content.find('</w:tr>', col_match.start()) + len('</w:tr>')
    header_row = xml_content[header_row_start:header_row_end]
    
    # 提取表头行中的所有单元格
    header_cells = re.findall(r'<w:tc>.*?</w:tc>', header_row, re.DOTALL)
    
    # 找到col_label在第几个单元格
    col_index = -1
    for i, cell in enumerate(header_cells):
        if col_label in cell:
            col_index = i
            break
    
    if col_index == -1:
        logger.warning(f"  未找到列 '{col_label}' 的索引")
        return xml_content, False
    
    logger.debug(f"  列 '{col_label}' 索引为 {col_index}")
    
    # 第二步：找到row_label所在的行
    row_match = re.search(f'>{re.escape(row_label)}</w:t>', xml_content)
    if not row_match:
        logger.warning(f"  未找到行标签: {row_label}")
        return xml_content, False
    
    row_start = xml_content.rfind('<w:tr', 0, row_match.start())
    row_end = xml_content.find('</w:tr>', row_match.end()) + len('</w:tr>')
    row_xml = xml_content[row_start:row_end]
    
    # 第三步：找到该行的第col_index个单元格
    row_cells = list(re.finditer(r'<w:tc>.*?</w:tc>', row_xml, re.DOTALL))
    
    if col_index >= len(row_cells):
        logger.warning(f"  行 '{row_label}' 只有 {len(row_cells)} 个单元格，无法访问第 {col_index} 列")
        return xml_content, False
    
    target_cell = row_cells[col_index]
    target_cell_xml = target_cell.group()
    
    # 第四步：在目标单元格中填入值
    # 查找空白段落模式
    empty_pattern = r'(</w:pPr>)(</w:p>)'
    match = re.search(empty_pattern, target_cell_xml)
    
    if match:
        # 在</w:pPr>后插入内容
        insert_pos = row_start + target_cell.start() + match.end(1)
        insert_text = f'<w:r><w:t>{value}</w:t></w:r>'
        new_xml = xml_content[:insert_pos] + insert_text + xml_content[insert_pos:]
        logger.info(f"  ✓ 在 '{row_label}' 行 '{col_label}' 列填入 '{value}'")
        return new_xml, True
    
    logger.warning(f"  未找到 '{row_label}' 行 '{col_label}' 列的空白单元格")
    return xml_content, False


def check_checkbox(xml_content: str, checkbox_text: str) -> tuple[str, bool]:
    """
    勾选复选框
    处理两种情况：
    1. □和文本在同一个<w:t>标签中
    2. □和文本分别在不同的<w:t>标签中
    """
    # 清理checkbox_text，移除可能的□符号
    clean_text = checkbox_text.replace('□', '').replace('☑', '').strip()
    
    logger.debug(f"  查找复选框: {clean_text}")
    
    # 情况1：□和文本在同一个标签 - 如 <w:t>□ISO9000</w:t>
    pattern1 = f'□{clean_text}'
    pattern1_space = f'□ {clean_text}'
    pattern1_space2 = f'□{clean_text} '
    
    for pattern in [pattern1, pattern1_space, pattern1_space2]:
        if pattern in xml_content:
            new_xml = xml_content.replace(pattern, pattern.replace('□', '☑'), 1)
            logger.info(f"  ✓ 勾选复选框: {clean_text}")
            return new_xml, True
    
    # 情况2：□和文本分开 - 如 <w:t>□</w:t></w:r><w:r>...<w:t>ISO9000</w:t>
    # 需要用正则查找 □</w:t> ... clean_text 的模式，然后将□替换为☑
    
    # 构建正则：找到 □ 后面紧跟的文本是 clean_text
    # 模式：□</w:t></w:r><w:r>...<w:t>clean_text
    pattern2 = rf'(□)(</w:t></w:r><w:r>.*?<w:t[^>]*>)\s*{re.escape(clean_text)}'
    match = re.search(pattern2, xml_content, re.DOTALL)
    if match:
        # 替换□为☑
        new_xml = xml_content[:match.start(1)] + '☑' + xml_content[match.end(1):]
        logger.info(f"  ✓ 勾选复选框（分离标签）: {clean_text}")
        return new_xml, True
    
    # 情况3：□在前面有空格的文本中 - 如 <w:t>      □</w:t></w:r><w:r>...<w:t>ISO14000</w:t>
    pattern3 = rf'(\s*□)(</w:t></w:r><w:r>.*?<w:t[^>]*>)\s*{re.escape(clean_text)}'
    match = re.search(pattern3, xml_content, re.DOTALL)
    if match:
        # 只替换□为☑，保留空格
        old_part = match.group(1)
        new_part = old_part.replace('□', '☑')
        new_xml = xml_content[:match.start(1)] + new_part + xml_content[match.end(1):]
        logger.info(f"  ✓ 勾选复选框（带空格）: {clean_text}")
        return new_xml, True
    
    logger.warning(f"  未找到复选框: {clean_text}")
    return xml_content, False


def process_document_with_knowledge(xml_content: str, chunks: list[dict], knowledge_base: list[dict]) -> tuple[str, list[dict]]:
    """处理文档：LLM分析 + 代码精准填入"""
    logger.info("=" * 60)
    logger.info("开始处理文档 - 智能分析+精准填入模式")
    logger.info(f"知识库条目: {[item['field_name'] + '=' + item['content'] for item in knowledge_base]}")
    
    if not knowledge_base:
        logger.warning("知识库为空")
        return xml_content, []
    
    mappings = analyze_document(xml_content, knowledge_base)
    
    if not mappings:
        logger.warning("未找到需要填入的内容")
        return xml_content, []
    
    logger.info(f"找到 {len(mappings)} 处需要处理")
    
    result_xml = xml_content
    success_count = 0
    modifications = []
    
    for mapping in mappings:
        op_type = mapping.get("type", "fill")
        success = False
        
        if op_type == "check":
            label = mapping.get("label", "")
            result_xml, success = check_checkbox(result_xml, label)
            modifications.append({"type": "check", "label": label, "status": "success" if success else "failed"})
        
        elif op_type == "fill_after_row":
            row_label = mapping.get("row_label", "")
            after_col = mapping.get("after_col", "")
            value = mapping.get("value", "")
            result_xml, success = find_and_fill_cross_table(result_xml, row_label, after_col, value)
            modifications.append({"type": "cross", "label": f"{row_label} x {after_col}", "value": value, "status": "success" if success else "failed"})
        
        else:  # fill
            label = mapping.get("label", "")
            value = mapping.get("value", "")
            result_xml, success = find_and_fill_after_label(result_xml, label, value)
            modifications.append({"type": "fill", "label": label, "value": value, "status": "success" if success else "failed"})
        
        if success:
            success_count += 1
    
    logger.info(f"成功处理 {success_count}/{len(mappings)} 处")
    logger.info("文档处理完成")
    logger.info("=" * 60)
    
    return result_xml, modifications
