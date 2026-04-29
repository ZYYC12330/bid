"""FastAPI 主入口"""
import os
import uuid
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services import knowledge_service, word_service, llm_service

app = FastAPI(title="Word文档知识库插入系统")

# 确保目录存在
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 静态文件服务
app.mount("/static", StaticFiles(directory="static"), name="static")


# ===== 数据模型 =====
class KnowledgeItem(BaseModel):
    field_name: str
    content: str
    description: str = ""


class KnowledgeUpdate(BaseModel):
    field_name: str
    content: str
    description: str = ""


# ===== 页面路由 =====
@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ===== 知识库API =====
@app.get("/api/knowledge")
async def get_knowledge():
    """获取所有知识条目"""
    return knowledge_service.get_all_knowledge()


@app.post("/api/knowledge")
async def add_knowledge(item: KnowledgeItem):
    """添加知识条目"""
    return knowledge_service.add_knowledge(
        item.field_name, item.content, item.description
    )


@app.put("/api/knowledge/{knowledge_id}")
async def update_knowledge(knowledge_id: str, item: KnowledgeUpdate):
    """更新知识条目"""
    result = knowledge_service.update_knowledge(
        knowledge_id, item.field_name, item.content, item.description
    )
    if result is None:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return result


@app.delete("/api/knowledge/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    """删除知识条目"""
    if knowledge_service.delete_knowledge(knowledge_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="知识条目不存在")


# ===== 文档处理API =====
@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传Word文档"""
    if not file.filename.endswith(('.docx', '.DOCX')):
        raise HTTPException(status_code=400, detail="只支持.docx格式文件")
    
    # 保存文件
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}.docx")
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    return {
        "file_id": file_id,
        "filename": file.filename,
        "message": "上传成功"
    }


@app.post("/api/process/{file_id}")
async def process_document(file_id: str):
    """处理文档，分析并插入知识库内容"""
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}.docx")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 获取知识库
    knowledge_base = knowledge_service.get_all_knowledge()
    if not knowledge_base:
        raise HTTPException(status_code=400, detail="知识库为空，请先添加知识条目")
    
    temp_dir = None
    try:
        # 转换为XML
        xml_content, temp_dir = word_service.word_to_xml(file_path)
        
        # 分块处理
        chunks = word_service.split_xml_to_chunks(xml_content)
        
        # LLM处理
        modified_xml, insertions = llm_service.process_document_with_knowledge(
            xml_content, chunks, knowledge_base
        )
        
        # 生成结果文件
        output_path = os.path.join(UPLOAD_DIR, f"{file_id}_processed.docx")
        word_service.xml_to_word(modified_xml, temp_dir, output_path)
        
        return {
            "success": True,
            "file_id": file_id,
            "insertions_count": len(insertions),
            "insertions": insertions,
            "download_url": f"/api/download/{file_id}"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        if temp_dir:
            word_service.cleanup_temp_dir(temp_dir)


@app.get("/api/download/{file_id}")
async def download_document(file_id: str):
    """下载处理后的文档"""
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}_processed.docx")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="处理后的文件不存在")
    
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"processed_{file_id}.docx"
    )


@app.get("/api/preview/{file_id}")
async def preview_document(file_id: str):
    """预览文档XML内容"""
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}.docx")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    temp_dir = None
    try:
        xml_content, temp_dir = word_service.word_to_xml(file_path)
        beautified = word_service.beautify_xml(xml_content)
        text_content = word_service.extract_text_from_xml(xml_content)
        
        return {
            "xml_preview": beautified[:5000],
            "text_content": text_content,
            "full_length": len(xml_content)
        }
    finally:
        if temp_dir:
            word_service.cleanup_temp_dir(temp_dir)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
