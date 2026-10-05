"""Synthetic reports with local codes; not vendor fixtures or a TID1500 claim."""

import io
from datetime import datetime, timezone

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ComprehensiveSRStorage, ExplicitVRLittleEndian, generate_uid


def make_json(modality="MAMMOGRAPHY", scenario="finding", study_uid=None):
    if modality == "MAMMOGRAPHY":
        categories = {
            "normal": (1, 2),
            "followup": (3, 2),
            "finding": (4, 2),
            "priority": (5, 2),
            "missing": (4, None),
        }
        if scenario not in categories:
            raise ValueError(f"Сценарий {scenario} не подходит для маммографии")
        right, left = categories[scenario]
        values = {"mmg_rads_right": right}
        if left is not None:
            values["mmg_rads_left"] = left
        conclusion = f"Правая молочная железа: BI-RADS {right}. Левая: BI-RADS {left}."
        if scenario == "missing":
            conclusion = "Синтетический неполный результат маммографии."
        params = {"mmg": values}
    elif modality == "CT_CHEST":
        counts = {"normal": 0, "finding": 1, "multiple": 3}
        if scenario not in counts:
            raise ValueError(f"Сценарий {scenario} не подходит для КТ")
        values = {"ct_lc_num": counts[scenario]}
        params = {"ct_lc": values}
        conclusion = {
            0: "КТ ОГК: лёгочные узлы не выявлены.",
            1: "КТ ОГК: один лёгочный узел. Синтетическое заключение.",
            3: "КТ ОГК: три лёгочных узла. Синтетическое заключение.",
        }[values["ct_lc_num"]]
    else:
        raise ValueError(f"Неизвестный тип исследования: {modality}")
    return {
        "synthetic": True,
        "studyIUID": study_uid or generate_uid(),
        "aiResult": {
            "modelId": 1000,
            "modelVersion": "synthetic-1",
            "report": conclusion,
            "conclusion": conclusion,
            "probParams": params,
        },
    }


def coded(code, meaning, scheme="ZDEMO"):
    ds = Dataset()
    ds.CodeValue, ds.CodingSchemeDesignator, ds.CodeMeaning = code, scheme, meaning
    return ds


def make_sr(raw: dict, modality: str) -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ComprehensiveSRStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = (
        meta.MediaStorageSOPClassUID,
        meta.MediaStorageSOPInstanceUID,
    )
    ds.StudyInstanceUID, ds.SeriesInstanceUID = raw["studyIUID"], generate_uid()
    ds.PatientID, ds.PatientName = "SYNTHETIC", "DEMO^SYNTHETIC"
    ds.PatientBirthDate, ds.PatientSex = "", ""
    ds.PatientIdentityRemoved = "YES"
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "SR", 1, 1
    ds.StudyID, ds.AccessionNumber, ds.ReferringPhysicianName = "", "", ""
    now = datetime.now(timezone.utc)
    ds.StudyDate = ds.ContentDate = now.strftime("%Y%m%d")
    ds.StudyTime = ds.ContentTime = now.strftime("%H%M%S")
    ds.Manufacturer = "Meditron Synthetic Fixtures"
    ds.CompletionFlag, ds.VerificationFlag = "COMPLETE", "UNVERIFIED"
    ds.ValueType, ds.ContinuityOfContent = "CONTAINER", "SEPARATE"
    ds.ConceptNameCodeSequence = Sequence([coded("report", "Synthetic report")])
    ds.ContentSequence = Sequence()
    text = Dataset()
    text.RelationshipType, text.ValueType = "CONTAINS", "TEXT"
    text.ConceptNameCodeSequence = Sequence([coded("conclusion", "Conclusion")])
    text.TextValue = raw["aiResult"]["conclusion"]
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.ContentSequence.append(text)
    group = "mmg" if modality == "MAMMOGRAPHY" else "ct_lc"
    for code, value in raw["aiResult"]["probParams"][group].items():
        item, measured = Dataset(), Dataset()
        item.RelationshipType, item.ValueType = "CONTAINS", "NUM"
        item.ConceptNameCodeSequence = Sequence([coded(code, code)])
        measured.NumericValue = value
        measured.MeasurementUnitsCodeSequence = Sequence([coded("1", "no units", "UCUM")])
        item.MeasuredValueSequence = Sequence([measured])
        ds.ContentSequence.append(item)
    output = io.BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()
