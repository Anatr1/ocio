"""Generate explicit pilot/production allowances from the sourced BOM."""
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "economics" / "data"


def build():
    raw = (DATA / "costs.json").read_bytes()
    costs = json.loads(raw)
    hardware = sum(item["cost_eur"] * item["quantity"] for item in costs["bom"])
    pilot_install = [
        {"name": "Installation labour", "quantity": 3, "cost_eur": 60, "unit": "hour"},
        {"name": "Camera calibration", "quantity": 1, "cost_eur": 70, "unit": "hour"},
        {"name": "Commissioning at an existing approved input", "quantity": 1, "cost_eur": 70, "unit": "hour"},
        {"name": "Connection consumables; approved input supplied by site owner", "quantity": 1, "cost_eur": 50},
    ]
    labour = sum(item["cost_eur"] * item["quantity"] for item in pilot_install)
    delivery = round((hardware + labour) * 1.10, 2)
    result = {
        "version": "cost-profiles-1", "currency": "EUR", "source_bom_sha256": hashlib.sha256(raw).hexdigest(),
        "default": "pilot", "profiles": {
            "pilot": {
                "label": "Pilot retrofit", "parameters": {
                    "installed_cost_eur": delivery, "annual_maintenance_eur": 80,
                    "platform_cost_eur": 2000, "supplier_gross_margin": .20,
                },
                "hardware_eur": round(hardware, 2), "installation": pilot_install,
                "contingency_fraction": .10, "contingency_eur": round((hardware + labour) * .10, 2),
                "status": "Conditional planning allowance, not a contractor quote",
                "conditions": [
                    "Site owner supplies an existing pole, mains power, permits and an approved fail-safe controller input.",
                    "No trenching, new lamps, traffic-lane closure, lift hire, new controller interface or product certification is included.",
                    "Existing software is reused; shared setup allowance is EUR2,000, not a new platform development budget.",
                    "Annual service delivery allowance is one EUR60 labour hour plus EUR20 spares; electricity is additional.",
                    "Small consumable spares are routine maintenance; major device replacements are budgeted separately in the lifecycle cash flows.",
                    "Indoor prototype camera in an enclosure still needs field validation; this budget does not certify an outdoor road product.",
                ],
            },
            "production": {
                "label": "Production rollout", "parameters": {
                    "installed_cost_eur": costs["defaults"]["installed_cost_eur"],
                    "annual_maintenance_eur": costs["defaults"]["annual_maintenance_eur"],
                    "platform_cost_eur": costs["defaults"]["platform_cost_eur"],
                    "supplier_gross_margin": .20,
                },
                "hardware_eur": round(hardware, 2), "installation": costs["installation"],
                "contingency_fraction": .20, "contingency_eur": costs["cost_build_up"]["contingency_eur"],
                "status": "Conservative planning allowance, not a contractor quote",
                "conditions": [costs["cost_build_up"]["notes"]],
            },
        },
        "notes": [
            "Hardware prices are unchanged. Lower pilot cost comes from explicit reuse and installation assumptions, not claimed supplier discounts.",
            "At 20% gross margin, sale price is delivery budget /0.8 and service fee is annual service delivery budget /0.8.",
            "The pilot profile must not be advertised as the unconditional cost to install at every Turin crossing.",
        ],
    }
    (DATA / "cost_profiles.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: p["parameters"] for key, p in result["profiles"].items()}, indent=2))


if __name__ == "__main__":
    build()
