"""VascGuide 共享枚举定义。

来源：`.workbuddy/spec/VascCase字段设计表.xlsx` · Sheet `04_枚举取值表`。
这些枚举被多个模型共用（VascCase、FinalRecommendation 等），故独立于 models 顶层，
避免循环引用。

命名约定：
  - 一律使用 ``StrEnum``（Python 3.11+），便于 JSON 序列化与审计落盘。
  - 中文取值直接作为成员值，保证与设计表、表1/表2 原文一致。
"""

from enum import StrEnum


def strip_enum_annotation(text: str) -> str:
    """去掉设计表「有（活动性）」式括号注释，返回核心取值。

    设计表「取值/枚举」列常把限定条件写在括号内（如「有（休克/低血压/晕厥）」、
    「有（影像/病原支持）」、「是（归因AAA）」）；枚举成员值只保留核心取值。

    抽取层若直接照抄设计表/表2 原文，必须先经本函数归一化，否则会被判为非法取值。
    这是**纯格式归一化**，不涉及任何临床推断。
    """
    text = text.strip()
    for open_ch, close_ch in (("（", "）"), ("(", ")")):
        idx = text.find(open_ch)
        if 0 < idx < len(text) - 1 and text.endswith(close_ch):
            return text[:idx].strip()
    return text


class Sex(StrEnum):
    """性别。阈值区分关键（男 55mm / 女 50mm）；未知不得默认男。"""

    MALE = "男"
    FEMALE = "女"
    UNKNOWN = "未知"


class TemporalStatus(StrEnum):
    """时态。关键：既往破裂 ≠ 当前破裂（表2 T27）。"""

    CURRENT = "当前"
    PAST = "既往"
    SUSPECTED = "疑似"


class DiagnosisCertainty(StrEnum):
    """诊断确定性。疑似高危不得因未确诊而延误。"""

    CONFIRMED = "确诊"
    SUSPECTED = "疑似"
    PENDING = "待排"
    NOT_MENTIONED = "未提及"


class RuptureStatus(StrEnum):
    """破裂状态。「排除破裂」→未破裂，不触发急诊（表2 T26/T33）。"""

    CONFIRMED = "明确破裂"
    SUSPECTED = "疑似破裂"
    INTACT = "未破裂"
    NOT_MENTIONED = "未提及"


class SymptomAAA(StrEnum):
    """AAA 归因性症状。需与否定/他因区分；「否认腹痛」不足以证明无症状。"""

    PRESENT = "有"
    ABSENT = "无"
    NOT_MENTIONED = "未提及"


class DiseaseCategory(StrEnum):
    """一级病种（对应表1 一级类别）。可多标签（list），见 O29。"""

    ASYMPTOMATIC = "1无症状AAA"
    SYMPTOMATIC_UNRUPTURED = "2症状性未破裂"
    RUPTURED_OR_SUSPECTED = "3破裂或疑似破裂"
    INFECTIOUS = "4感染性"
    OTHER_SPECIAL = "5其他特殊"
    ILIAC_ANEURYSM = "6髂动脉瘤"
    POSTOPERATIVE = "7术后状态"


class PriorRepair(StrEnum):
    """既往主动脉修复史。术后与术前走不同路径，不可混淆。"""

    NONE = "无"
    EVAR = "EVAR"
    OSR = "OSR"
    FEVAR = "FEVAR"
    BEVAR = "BEVAR"
    OTHER = "其他"


class EndoleakType(StrEnum):
    """内漏类型。Ⅰ/Ⅲ型高危；稳定Ⅱ型可走指南（表2 T10）。"""

    NONE = "无"
    IA = "Ia"
    IB = "Ib"
    IC = "Ic"
    II = "II"
    IIIA = "IIIa"
    IIIB = "IIIb"
    IV = "IV"
    UNKNOWN = "不明"


class CKDStage(StrEnum):
    """CKD 分期。≥3 触发复杂；孤立一次肌酐异常不能确诊分期。"""

    NONE = "无"
    S1 = "1"
    S2 = "2"
    S3 = "3"
    S4 = "4"
    S5 = "5"
    NOT_MENTIONED = "未提及"


class HeartFailureNYHA(StrEnum):
    """心衰分级。NYHA≥III 触发复杂。"""

    NONE = "无"
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    NOT_MENTIONED = "未提及"


class RouteMode(StrEnum):
    """最终路由模式。优先级：急诊 > 复杂 > 指南。"""

    EMERGENCY = "急诊模式"
    COMPLEX = "复杂模式"
    GUIDELINE = "指南模式"


class YesNoUnknown(StrEnum):
    """通用三态：有 / 无 / 未提及。用于合并症、证据类字段。"""

    YES = "有"
    NO = "无"
    NOT_MENTIONED = "未提及"


class InfectionEvidence(StrEnum):
    """感染证据（**四态**）。设计表取值：有（影像/病原支持）/ 无 / 疑似 / 未提及。

    关键：「疑似」是独立取值，**不得被当作「有」**（仅发热/菌血症不足以确诊，O21）。
    若用 :class:`YesNoUnknown` 承载会丢掉「疑似」，故独立成类。
    """

    YES = "有"
    NO = "无"
    SUSPECTED = "疑似"
    NOT_MENTIONED = "未提及"


class PainAttribution(StrEnum):
    """疼痛归因是否已核实（**三态**）。设计表取值：是（归因AAA）/ 否 / 未核实。

    关键：「未核实」与「否」含义不同——「否认腹痛」不足以证明无症状（O03）。
    """

    ATTRIBUTED_TO_AAA = "是"
    NOT_ATTRIBUTED = "否"
    UNVERIFIED = "未核实"


class Tortuosity(StrEnum):
    """迂曲 / 极度成角（**三态**）。设计表取值：有 / 无 / 未描述。O19（>90° 触发复杂）。"""

    PRESENT = "有"
    ABSENT = "无"
    NOT_DESCRIBED = "未描述"


class LesionMorphology(StrEnum):
    """瘤体形态。设计表取值：梭形 / 囊状 / 不规则 / 未描述。

    形态异常独立于直径阈值（表1 M02 / R008 / R040）。自由文本经
    :meth:`normalize` 归一化后落库。
    """

    FUSIFORM = "梭形"
    SACCULAR = "囊状"
    IRREGULAR = "不规则"
    NOT_DESCRIBED = "未描述"

    @classmethod
    def normalize(cls, text: str | None) -> "LesionMorphology | None":
        """自由文本 → 枚举。

        未识别**直接报错**，不得猜测（治理红线：不得脑补，交人工复核）。
        """
        if text is None:
            return None
        raw = strip_enum_annotation(str(text))
        if not raw:
            return None
        low = raw.lower()
        for member in cls:
            if low == member.value.lower():
                return member
        keywords = (
            ("囊状", cls.SACCULAR),
            ("梭形", cls.FUSIFORM),
            ("不规则", cls.IRREGULAR),
            ("未描述", cls.NOT_DESCRIBED),
        )
        for kw, member in keywords:
            if kw in low:
                return member
        raise ValueError(
            f"lesion_morphology 无法归一化：{raw!r}。允许取值 {[m.value for m in cls]}；"
            "未识别不得猜测，请交人工复核。"
        )


class AnatomyLevel(StrEnum):
    """解剖分型。设计表取值：肾下 / 短颈肾下 / 近肾 / 旁肾 / 近内脏 / IV型TAAA。

    近肾 / 旁肾 / 近内脏 / IV型TAAA / 短颈肾下 → 复杂解剖（O22、表1 近肾/旁肾子类）。
    自由文本经 :meth:`normalize` 归一化后落库。
    """

    INFRARENAL = "肾下"
    SHORT_NECK_INFRARENAL = "短颈肾下"
    JUXTARENAL = "近肾"
    PARARENAL = "旁肾"
    PARAVISCERAL = "近内脏"
    TYPE_IV_TAAA = "IV型TAAA"

    @classmethod
    def normalize(cls, text: str | None) -> "AnatomyLevel | None":
        """自由文本 → 枚举（如「近肾腹主动脉瘤」→ ``JUXTARENAL``）。

        关键词表**具体优先**：必须先判「短颈」再判「肾下」，否则
        「短颈肾下」会被误归为普通肾下型。未识别直接报错。
        """
        if text is None:
            return None
        raw = strip_enum_annotation(str(text))
        if not raw:
            return None
        low = raw.lower()
        for member in cls:
            if low == member.value.lower():
                return member
        keywords = (
            ("短颈", cls.SHORT_NECK_INFRARENAL),
            ("近内脏", cls.PARAVISCERAL),
            ("旁内脏", cls.PARAVISCERAL),
            ("iv型", cls.TYPE_IV_TAAA),
            ("type iv", cls.TYPE_IV_TAAA),
            ("近肾", cls.JUXTARENAL),
            ("旁肾", cls.PARARENAL),
            ("肾下", cls.INFRARENAL),
        )
        for kw, member in keywords:
            if kw in low:
                return member
        raise ValueError(
            f"anatomy_level 无法归一化：{raw!r}。允许取值 {[m.value for m in cls]}；"
            "未识别不得猜测，请交人工复核。"
        )


class MalignancyStatus(StrEnum):
    """合并恶性肿瘤（**四态**）。设计表取值：有（活动性）/ 无 / 既往已愈 / 未提及。

    仅「有（活动性）」参与特殊病变判定（O21 / R051）；「既往已愈」不触发。
    """

    ACTIVE = "有"
    NONE = "无"
    RESOLVED = "既往已愈"
    NOT_MENTIONED = "未提及"


class FieldWriter(StrEnum):
    """字段写入者 —— 审计归责用：区分 LLM 判断 / 规则判断 / 人工覆写。"""

    LLM = "LLM"
    IMAGING = "影像量化器"
    HUMAN = "人工"
    SYSTEM = "系统"


__all__ = [
    "AnatomyLevel",
    "CKDStage",
    "DiagnosisCertainty",
    "DiseaseCategory",
    "EndoleakType",
    "FieldWriter",
    "HeartFailureNYHA",
    "InfectionEvidence",
    "LesionMorphology",
    "MalignancyStatus",
    "PainAttribution",
    "PriorRepair",
    "RouteMode",
    "RuptureStatus",
    "Sex",
    "SymptomAAA",
    "TemporalStatus",
    "Tortuosity",
    "YesNoUnknown",
    "strip_enum_annotation",
]
