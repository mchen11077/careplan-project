"""
Adapter Pattern for order ingestion.

Every input source (web form, a clinic's JSON feed, a pharma partner's XML file) is converted into one
internal format, InternalOrder. Validation, duplicate detection and care plan generation only ever see
InternalOrder, so adding a new source means writing one new adapter class and registering it; no
business logic changes.

This module deliberately has no Django imports so the same code runs in the Django API and in the
AWS Lambda `create_order` function.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Type, Union


class AdapterError(ValueError):
    """Raw payload could not be parsed into an InternalOrder."""


class UnknownSourceError(AdapterError):
    """No adapter is registered for the requested source."""


@dataclass
class InternalOrder:
    """The single internal representation every source is mapped to."""

    patient_mrn: str
    patient_first_name: str
    patient_last_name: str
    primary_diagnosis_code: str
    provider_npi: str
    provider_name: str
    medication_name: str
    patient_records: str
    patient_date_of_birth: Optional[str] = None  # ISO yyyy-mm-dd
    patient_sex: Optional[str] = None
    patient_weight_kg: Optional[str] = None
    patient_allergies: Optional[str] = None
    primary_diagnosis_description: str = ""
    additional_diagnoses: List[str] = field(default_factory=list)
    medication_history: List[str] = field(default_factory=list)
    confirm_not_duplicate: bool = False
    source: str = "web_form"

    def to_serializer_data(self) -> Dict[str, Any]:
        """Flat dict accepted by OrderCreateSerializer (drops None values and the source tag)."""
        data = asdict(self)
        data.pop("source")
        return {k: v for k, v in data.items() if v is not None}


class BaseOrderAdapter(ABC):
    source: str = ""

    @abstractmethod
    def parse(self, raw: Union[str, bytes, Dict[str, Any]]) -> InternalOrder:
        """Convert a raw payload from this source into an InternalOrder."""


_REGISTRY: Dict[str, Type[BaseOrderAdapter]] = {}


def register(cls: Type[BaseOrderAdapter]) -> Type[BaseOrderAdapter]:
    _REGISTRY[cls.source] = cls
    return cls


def get_adapter(source: str) -> BaseOrderAdapter:
    try:
        return _REGISTRY[source]()
    except KeyError:
        raise UnknownSourceError(
            f"Unknown source '{source}'. Supported: {', '.join(sorted(_REGISTRY))}"
        ) from None


def supported_sources() -> List[str]:
    return sorted(_REGISTRY)


def _require(value: Any, name: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AdapterError(f"Missing required field: {name}")
    return str(value).strip()


def _as_dict(raw: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"Invalid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise AdapterError("JSON payload must be an object")
    return data


@register
class WebFormAdapter(BaseOrderAdapter):
    """Our own React form. Field names already match the internal format."""

    source = "web_form"

    def parse(self, raw):
        d = _as_dict(raw)
        return InternalOrder(
            patient_mrn=_require(d.get("patient_mrn"), "patient_mrn"),
            patient_first_name=_require(d.get("patient_first_name"), "patient_first_name"),
            patient_last_name=_require(d.get("patient_last_name"), "patient_last_name"),
            primary_diagnosis_code=_require(d.get("primary_diagnosis_code"), "primary_diagnosis_code"),
            provider_npi=_require(d.get("provider_npi"), "provider_npi"),
            provider_name=_require(d.get("provider_name"), "provider_name"),
            medication_name=_require(d.get("medication_name"), "medication_name"),
            patient_records=str(d.get("patient_records") or ""),
            patient_date_of_birth=d.get("patient_date_of_birth") or None,
            patient_sex=d.get("patient_sex") or None,
            patient_weight_kg=d.get("patient_weight_kg") or None,
            patient_allergies=d.get("patient_allergies") or None,
            primary_diagnosis_description=d.get("primary_diagnosis_description") or "",
            additional_diagnoses=list(d.get("additional_diagnoses") or []),
            medication_history=list(d.get("medication_history") or []),
            confirm_not_duplicate=bool(d.get("confirm_not_duplicate", False)),
            source=self.source,
        )


@register
class ClinicJSONAdapter(BaseOrderAdapter):
    """
    Partner clinic's nested JSON, e.g.
    {"patient": {"mrn": "...", "name": {"first": "...", "last": "..."}, "dob": "...", "sex": "F",
                 "weightKg": 70, "allergies": ["Codeine"]},
     "prescriber": {"npi": "...", "fullName": "..."},
     "rx": {"drug": "...", "diagnosis": {"icd10": "...", "description": "..."},
            "secondaryDiagnoses": ["E11.9"], "currentMeds": ["Metformin 1000mg"]},
     "clinicalNotes": "...", "confirmNotDuplicate": false}
    """

    source = "clinic_json"
    _SEX = {"F": "Female", "M": "Male", "O": "Other", "FEMALE": "Female", "MALE": "Male", "OTHER": "Other"}

    def parse(self, raw):
        d = _as_dict(raw)
        patient = d.get("patient") or {}
        name = patient.get("name") or {}
        prescriber = d.get("prescriber") or {}
        rx = d.get("rx") or {}
        diagnosis = rx.get("diagnosis") or {}
        sex = patient.get("sex")
        allergies = patient.get("allergies")
        if isinstance(allergies, list):
            allergies = ", ".join(allergies)
        weight = patient.get("weightKg")
        return InternalOrder(
            patient_mrn=_require(patient.get("mrn"), "patient.mrn"),
            patient_first_name=_require(name.get("first"), "patient.name.first"),
            patient_last_name=_require(name.get("last"), "patient.name.last"),
            primary_diagnosis_code=_require(diagnosis.get("icd10"), "rx.diagnosis.icd10"),
            provider_npi=_require(prescriber.get("npi"), "prescriber.npi"),
            provider_name=_require(prescriber.get("fullName"), "prescriber.fullName"),
            medication_name=_require(rx.get("drug"), "rx.drug"),
            patient_records=_require(d.get("clinicalNotes"), "clinicalNotes"),
            patient_date_of_birth=patient.get("dob") or None,
            patient_sex=self._SEX.get(str(sex).upper()) if sex else None,
            patient_weight_kg=str(weight) if weight is not None else None,
            patient_allergies=allergies or None,
            primary_diagnosis_description=diagnosis.get("description") or "",
            additional_diagnoses=list(rx.get("secondaryDiagnoses") or []),
            medication_history=list(rx.get("currentMeds") or []),
            confirm_not_duplicate=bool(d.get("confirmNotDuplicate", False)),
            source=self.source,
        )


@register
class PharmaXMLAdapter(BaseOrderAdapter):
    """
    Pharma partner's XML, e.g.
    <CarePlanOrder confirmNotDuplicate="false">
      <Patient mrn="123456" dob="1960-10-21" sex="Female" weightKg="70">
        <FirstName>Jane</FirstName><LastName>Doe</LastName>
        <Allergies>Codeine</Allergies>
        <HomeMedications><Medication>Metformin 1000mg</Medication></HomeMedications>
      </Patient>
      <Prescriber npi="1234567893"><Name>Dr. Jane Smith</Name></Prescriber>
      <Therapy drug="IVIG">
        <Diagnosis code="G70.00" primary="true">Myasthenia gravis</Diagnosis>
        <Diagnosis code="I10"/>
      </Therapy>
      <ClinicalNotes>...</ClinicalNotes>
    </CarePlanOrder>
    """

    source = "pharma_xml"

    def parse(self, raw):
        if isinstance(raw, dict):
            raise AdapterError("pharma_xml expects an XML document, not JSON")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise AdapterError(f"Invalid XML: {exc}") from None
        patient = root.find("Patient")
        prescriber = root.find("Prescriber")
        therapy = root.find("Therapy")
        if patient is None or prescriber is None or therapy is None:
            raise AdapterError("XML must contain Patient, Prescriber and Therapy elements")

        diagnoses = therapy.findall("Diagnosis")
        primary = next((dx for dx in diagnoses if dx.get("primary") == "true"), diagnoses[0] if diagnoses else None)
        if primary is None:
            raise AdapterError("Missing required field: Therapy/Diagnosis")
        secondary = [dx.get("code") for dx in diagnoses if dx is not primary and dx.get("code")]

        return InternalOrder(
            patient_mrn=_require(patient.get("mrn"), "Patient@mrn"),
            patient_first_name=_require(patient.findtext("FirstName"), "Patient/FirstName"),
            patient_last_name=_require(patient.findtext("LastName"), "Patient/LastName"),
            primary_diagnosis_code=_require(primary.get("code"), "Diagnosis@code"),
            provider_npi=_require(prescriber.get("npi"), "Prescriber@npi"),
            provider_name=_require(prescriber.findtext("Name"), "Prescriber/Name"),
            medication_name=_require(therapy.get("drug"), "Therapy@drug"),
            patient_records=_require(root.findtext("ClinicalNotes"), "ClinicalNotes"),
            patient_date_of_birth=patient.get("dob") or None,
            patient_sex=patient.get("sex") or None,
            patient_weight_kg=patient.get("weightKg") or None,
            patient_allergies=(patient.findtext("Allergies") or "").strip() or None,
            primary_diagnosis_description=(primary.text or "").strip(),
            additional_diagnoses=secondary,
            medication_history=[m.text.strip() for m in patient.findall("HomeMedications/Medication") if m.text],
            confirm_not_duplicate=root.get("confirmNotDuplicate", "false").lower() == "true",
            source=self.source,
        )
