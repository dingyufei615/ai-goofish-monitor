import json
import os
from typing import List, Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# 全局变量存储embedding模型和配置
_embedding_model = None
_embedding_config = None


def initialize_embedding_filter():
    """
    初始化embedding过滤器，加载模型和配置
    """
    global _embedding_model, _embedding_config
    
    # 检查是否已经初始化
    if _embedding_model is not None:
        return
    
    try:
        # 加载embedding模型
        print("正在加载embedding模型...")
        _embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        print("embedding模型加载完成。")
    except Exception as e:
        print(f"加载embedding模型时出错: {e}")
        _embedding_model = None


def calculate_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本之间的余弦相似度
    
    Args:
        text1: 第一个文本
        text2: 第二个文本
        
    Returns:
        float: 余弦相似度值 (0-1之间)
    """
    global _embedding_model
    
    if _embedding_model is None:
        return 0.0
    
    try:
        # 生成文本的embedding向量
        embeddings = _embedding_model.encode([text1, text2])
        
        # 计算余弦相似度
        similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
        
        return float(similarity)
    except Exception as e:
        print(f"计算文本相似度时出错: {e}")
        return 0.0


def filter_by_similarity(item_data: dict, task_config: dict) -> bool:
    """
    根据embedding相似度过滤商品
    
    Args:
        item_data: 商品数据
        task_config: 任务配置
        
    Returns:
        bool: True表示通过过滤，False表示未通过过滤
    """
    global _embedding_model
    
    # 检查是否启用了embedding过滤
    embedding_filter_config = task_config.get('embedding_filter')
    if not embedding_filter_config or _embedding_model is None:
        return True  # 未启用过滤则直接通过
    
    # 获取配置参数
    reference_texts = embedding_filter_config.get('reference_texts', [])
    threshold = embedding_filter_config.get('threshold', 0.5)
    
    # 如果没有参考文本，则直接通过
    if not reference_texts:
        return True
    
    # 获取商品标题
    title = item_data.get('商品标题', '')
    if not title:
        return True  # 没有标题则直接通过
    
    # 计算商品标题与每个参考文本的相似度
    max_similarity = 0.0
    for ref_text in reference_texts:
        similarity = calculate_similarity(title, ref_text)
        if similarity > max_similarity:
            max_similarity = similarity
            
        # 如果已经超过了阈值，可以提前退出
        if max_similarity >= threshold:
            break
    
    # 判断是否通过过滤
    is_passed = max_similarity >= threshold
    
    if not is_passed:
        print(f"   -> 商品 '{title[:30]}...' 未通过embedding相似度过滤 (相似度: {max_similarity:.3f}, 阈值: {threshold})")
    
    return is_passed