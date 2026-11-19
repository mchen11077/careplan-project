import re
from datetime import date


class IntakeError(ValueError):
    pass


def normalize(raw):
    if not isinstance(raw, dict):
        raise IntakeError("Expected an object.")
    fields = ["patient_mrn", "patient_first_name", "patient_last_name",
              "patient_date_of_birth", "primary_diagnosis_code", "medication_name",
              "provider_name", "provider_npi"]
    data = {}
    for field in fields:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise IntakeError(f"{field}: enter a value of 1–200 characters.")
        data[field] = value.strip()
    if not re.fullmatch(r"\d{6}", data["patient_mrn"]):
        raise IntakeError("MRN must contain six digits.")
    if not re.fullmatch(r"\d{10}", data["provider_npi"]):
        raise IntakeError("Provider NPI must contain ten digits.")
    data["primary_diagnosis_code"] = data["primary_diagnosis_code"].upper()
    if not re.fullmatch(r"[A-Z][0-9][A-Z0-9](?:\.[A-Z0-9]{1,4})?", data["primary_diagnosis_code"]):
        raise IntakeError("Enter an ICD-10 code such as Z00.00.")
    try:
        birthday = date.fromisoformat(data["patient_date_of_birth"])
        if birthday > date.today():
            raise ValueError()
    except ValueError:
        raise IntakeError("Enter a valid date of birth in the past.") from None
    for field in ["patient_records", "medication_history", "additional_diagnoses"]:
        value = raw.get(field, "")
        if not isinstance(value, str) or len(value) > 12000:
            raise IntakeError(f"{field}: enter text up to 12,000 characters.")
        data[field] = value.strip()
    if "confirm_warnings" in raw and not isinstance(raw["confirm_warnings"], bool):
        raise IntakeError("confirm_warnings must be a boolean.")
    return data


def duplicate_warnings(data, existing):
    warnings = set()
    for other in existing:
        p = other.payload
        same_mrn = other.mrn == data["patient_mrn"]
        same_person = (
            p["patient_first_name"].casefold() == data["patient_first_name"].casefold()
            and p["patient_last_name"].casefold() == data["patient_last_name"].casefold()
            and p["patient_date_of_birth"] == data["patient_date_of_birth"]
        )
        if same_mrn and not same_person:
            warnings.add("This MRN already has different patient details. Confirm the identity.")
        if same_person and not same_mrn:
            warnings.add("A matching name and birth date already exists with a different MRN.")
        if same_mrn and other.medication == data["medication_name"].casefold():
            warnings.add("This patient has a previous order for this medication. Confirm this refill.")
    return sorted(warnings)
