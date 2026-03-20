"""
Skill 渲染事务 (Affair)。
将输入的 Skill 路径和参数，通过引擎的渲染工具转换为最终的 Prompt 文本。
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional

# 导入引擎层的工具
try:
    from autodoengine.utils.skill_renderer import SkillRenderer
except ImportError:
    # 也可以降级使用本地或者报错，这里假设环境已配置好
    SkillRenderer = None

class SkillRenderAffair:
    """
    Skill 渲染事务类。
    
    负责：
    1. 接收 skill_path 和 params。
    2. 执行参数校验。
    3. 调用渲染引擎生成结果。
    4. 返回渲染后的文本及元数据。
    """

    def __init__(self, renderer: Optional[SkillRenderer] = None):
        if renderer:
            self.renderer = renderer
        elif SkillRenderer:
            self.renderer = SkillRenderer()
        else:
            self.renderer = None

    def run(self, skill_path: str | Path, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行渲染事务。
        
        Args:
            skill_path: SKILL.md 文件路径。
            params: 渲染所需的参数字典。
            
        Returns:
            Dict[str, Any]: 包含渲染结果 'prompt' 和元数据 'meta' 的字典。
        """
        if not self.renderer:
            return {
                "status": "FAIL",
                "error": "SkillRenderer 未在环境中找到，请检查 autodo-engine 安装情况。"
            }

        try:
            skill_path_str = str(skill_path)
            # 获取元数据以便返回给调用方（例如前端 UI 展示字段描述）
            meta, _ = self.renderer.load_skill(skill_path_str)
            
            # 执行渲染
            rendered_prompt = self.renderer.render(skill_path_str, params)
            
            return {
                "status": "PASS",
                "prompt": rendered_prompt,
                "meta": meta,
                "skill_name": meta.get("name", "unknown"),
                "skill_path": skill_path_str
            }
        except Exception as e:
            return {
                "status": "FAIL",
                "error": str(e)
            }

def main(skill_path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    事务入口点。
    """
    affair = SkillRenderAffair()
    return affair.run(skill_path, params)
