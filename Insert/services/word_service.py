"""Word文档处理服务模块"""
import os
import shutil
import zipfile
import tempfile
from bs4 import BeautifulSoup


def word_to_xml(docx_path: str) -> tuple[str, str]:
    """
    将Word文档转换为XML
    
    Args:
        docx_path: Word文档路径
        
    Returns:
        tuple: (document.xml内容, 临时解压目录路径)
    """
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    # 解压docx文件
    with zipfile.ZipFile(docx_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    
    # 读取document.xml
    document_xml_path = os.path.join(temp_dir, "word", "document.xml")
    with open(document_xml_path, 'r', encoding='utf-8') as f:
        xml_content = f.read()
    
    return xml_content, temp_dir


def beautify_xml(xml_content: str) -> str:
    """
    美化XML格式
    
    Args:
        xml_content: 原始XML内容
        
    Returns:
        格式化后的XML内容
    """
    soup = BeautifulSoup(xml_content, 'lxml-xml')
    return soup.prettify()


def xml_to_word(xml_content: str, temp_dir: str, output_path: str) -> str:
    """
    将修改后的XML转换回Word文档
    
    Args:
        xml_content: 修改后的XML内容
        temp_dir: 临时解压目录路径
        output_path: 输出文件路径
        
    Returns:
        输出文件路径
    """
    # 写入修改后的document.xml
    document_xml_path = os.path.join(temp_dir, "word", "document.xml")
    with open(document_xml_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)
    
    # 重新打包为docx
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
    
    return output_path


def cleanup_temp_dir(temp_dir: str):
    """
    清理临时目录
    
    Args:
        temp_dir: 临时目录路径
    """
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


def extract_text_from_xml(xml_content: str) -> str:
    """
    从XML中提取纯文本内容
    
    Args:
        xml_content: XML内容
        
    Returns:
        提取的文本内容
    """
    soup = BeautifulSoup(xml_content, 'lxml-xml')
    
    # 查找所有文本节点 (w:t 标签)
    text_nodes = soup.find_all('w:t')
    
    texts = []
    for node in text_nodes:
        if node.string:
            texts.append(node.string)
    
    return ' '.join(texts)


def split_xml_to_chunks(xml_content: str, max_chunk_size: int = 4000) -> list[dict]:
    """
    将XML内容分块处理
    
    Args:
        xml_content: XML内容
        max_chunk_size: 每个块的最大字符数
        
    Returns:
        分块列表，每个块包含 {start_index, end_index, content, text_preview}
    """
    soup = BeautifulSoup(xml_content, 'lxml-xml')
    body = soup.find('w:body')
    
    if not body:
        return [{"start_index": 0, "end_index": len(xml_content), "content": xml_content, "text_preview": ""}]
    
    chunks = []
    current_chunk = []
    current_size = 0
    chunk_start = 0
    
    # 按段落分块 (w:p 标签)
    paragraphs = body.find_all('w:p', recursive=False)
    
    for i, p in enumerate(paragraphs):
        p_str = str(p)
        p_size = len(p_str)
        
        if current_size + p_size > max_chunk_size and current_chunk:
            # 保存当前块
            chunk_content = ''.join(str(item) for item in current_chunk)
            text_preview = extract_text_from_xml(chunk_content)[:200]
            chunks.append({
                "chunk_index": len(chunks),
                "content": chunk_content,
                "text_preview": text_preview,
                "paragraph_range": (chunk_start, i - 1)
            })
            current_chunk = [p]
            current_size = p_size
            chunk_start = i
        else:
            current_chunk.append(p)
            current_size += p_size
    
    # 保存最后一个块
    if current_chunk:
        chunk_content = ''.join(str(item) for item in current_chunk)
        text_preview = extract_text_from_xml(chunk_content)[:200]
        chunks.append({
            "chunk_index": len(chunks),
            "content": chunk_content,
            "text_preview": text_preview,
            "paragraph_range": (chunk_start, len(paragraphs) - 1)
        })
    
    return chunks
