"""Visual checklist v2. Not-visible is distinct from a visible defect."""
CHECKLIST_VERSION = "visual-v2"
CHECKS = {
    "finger_count": "手指数量：清晰可见的完整手是否多指、少指；逐只手说明",
    "hand_structure": "手部结构：手指粘连、分叉、异常弯折，手掌与手腕连接",
    "limb_count": "肢体数量：是否多手臂、多腿、重复或缺失肢体",
    "joint_connection": "关节与连接：肩肘腕髋膝踝是否错接、扭曲、穿插",
    "face_structure": "面部结构：眼睛、瞳孔、嘴、牙齿、耳朵是否重复、融合或错位",
    "body_proportion": "身体比例：头身、躯干、四肢是否有非风格性异常",
    "object_structure": "物体结构：主体轮廓、零件数量和连接是否破损或融化",
    "text_legibility": "文字：逐字核对指定文字，检查错字、缺字、乱码与变形",
    "edge_integrity": "边缘与融合：重影、断边、主体与背景粘连",
    "contact_occlusion": "接触与遮挡：握持、脚底落地、前后遮挡是否穿模或悬空",
    "light_perspective": "光影与透视：光源、投影、反射、消失点是否矛盾",
    "surface_texture": "表面细节：皮肤、毛发、衣物或材质是否涂抹、重复、噪点异常",
}
STATUS_SCORES = {"pass": 5, "minor": 4, "major": 2, "severe": 1,
                 "unassessable": None, "not_applicable": None}
