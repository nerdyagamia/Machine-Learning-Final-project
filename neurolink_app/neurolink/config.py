"""Paths, defaults and static content. No Streamlit imports here."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

# The partners' files live here, UNMODIFIED (read-only for the app).
MODEL_DIR = Path(os.environ.get("NEUROLINK_MODEL_DIR", APP_DIR / "Data_for_deployment"))
# Recorded EEG trials used to simulate the helmet stream (UNMODIFIED copies from the dataset).
REPLAY_DIR = Path(os.environ.get("NEUROLINK_REPLAY_DIR", APP_DIR / "replay_data"))
# Everything the app writes (database, offline cache) goes here.
DATA_DIR = Path(os.environ.get("NEUROLINK_DATA_DIR", APP_DIR / "neurolink_data"))
CACHE_DIR = DATA_DIR / "offline_cache"
DB_PATH = DATA_DIR / "neurolink.db"

MODEL_FILE = "csp_svm_baseline.joblib"
META_FILE = "csp_svm_baseline_meta.json"
PRE_CONFIG_FILE = "preprocessing_config.json"
PREPROCESS_MODULE_FILE = "bci_preprocess.py"

REPLAY_EEG = "eeg_X_test.npy"      # (n_trials, n_times, n_channels) float32, already preprocessed
REPLAY_LABELS = "y_test.npy"       # 0 = Left, 1 = Right
REPLAY_IDS = "ids_test.csv"

# --------------------------------------------------------------------------- preferences
DEFAULT_PREFS: dict = {
    "patient_name": "Patient",
    "language": "en",              # "en" | "ar"
    "timezone": "Africa/Cairo",
    "tts_enabled": True,
    "tts_rate": 1.0,
    "tts_pitch": 1.0,
    "tts_volume": 1.0,
    "alarm_sound": True,
    "large_buttons": False,
    "high_contrast": False,
    # helmet / mobility
    "confidence_gate": 0.51,       # decisions below this probability are ignored
    "speed_mps": 1.0,
    "turn_step_deg": 15,
    # contacts
    "caregiver_name": "Caregiver",
    "caregiver_phone": "",
    "caregiver_email": "",
    "emergency_number": "123",     # Egypt ambulance
    "webhook_url": "",             # optional: POST alerts as JSON to this URL
    "notify_on_need": True,        # needs spoken in Communication also notify the caregiver
    "caregiver_pin": "1234",
    # location
    "location_name": "Alexandria, Egypt",
    "lat": 31.2001,
    "lon": 29.9187,
    # safety
    "stop_distance_m": 1.2,
    "slow_distance_m": 3.0,
    "vehicle_caution_s": 8.0,
    "vehicle_danger_s": 4.0,
    "auto_stop": True,
    # offline
    "offline_forced": False,       # simulate a poor connection
}

# --------------------------------------------------------------------------- communication
# key, English, Arabic, icon, colour class
CORE_PHRASES = [
    ("thirsty", "I'm thirsty", "أنا عطشان", "🥤", "thirsty"),
    ("hungry", "I'm hungry", "أنا جعان", "🍴", "hungry"),
    ("help", "I need help", "محتاج مساعدة", "❗", "help"),
    ("thanks", "Thank you", "شكراً", "❤️", "thanks"),
    ("yes", "Yes", "نعم", "✔️", "yes"),
    ("no", "No", "لا", "✖️", "no"),
]
MORE_PHRASES = [
    ("pain", "I'm in pain", "أشعر بألم"),
    ("cold", "I'm cold", "أنا بردان"),
    ("hot", "I'm hot", "أشعر بالحر"),
    ("bathroom", "I need the bathroom", "أحتاج إلى الحمام"),
    ("tired", "I'm tired", "أنا تعبان"),
    ("wait", "Please wait", "من فضلك انتظر"),
    ("call", "Please call my caregiver", "من فضلك اتصل بمقدم الرعاية"),
    ("morning", "Good morning", "صباح الخير"),
]
# phrases that also create an assistance request for the caregiver dashboard
NEED_PHRASES = {"thirsty", "hungry", "help", "pain", "cold", "hot", "bathroom", "tired", "call"}

# --------------------------------------------------------------------------- daily assistant
DEFAULT_REMINDERS = [
    # title, HH:MM, kind
    ("Take morning medication", "08:00", "medication"),
    ("Drink a glass of water", "10:30", "hydration"),
    ("Pressure relief / change position", "14:00", "therapy"),
    ("Drink a glass of water", "16:00", "hydration"),
    ("Take evening medication", "20:00", "medication"),
]
REMINDER_ICONS = {"medication": "💊", "hydration": "💧", "therapy": "🧘", "appointment": "📅", "other": "⏰"}

ROUTINES = {
    "Morning routine": ["Wash face and brush teeth", "Take morning medication", "Breakfast", "Stretching / range-of-motion exercises", "Check wheelchair battery"],
    "Evening routine": ["Dinner", "Take evening medication", "Charge helmet and phone", "Skin and pressure check", "Prepare for bed"],
}

DAILY_NEEDS = [
    ("water", "💧", "Water", "I need some water"),
    ("food", "🍽️", "Food", "I would like something to eat"),
    ("bathroom", "🚻", "Bathroom", "I need the bathroom"),
    ("position", "🛏️", "Change position", "Please help me change position"),
    ("temperature", "🌡️", "Temperature", "Please adjust the temperature"),
    ("tv", "📺", "TV / Entertainment", "Please turn on the TV"),
    ("medication", "💊", "Medication", "I need my medication"),
    ("call", "📞", "Make a call", "Please help me make a phone call"),
]

# Phone / device controls (mirrors the Android action list in the reference screenshot).
PHONE_ACTIONS = {
    "Sound": [
        ("vol_up", "🔊", "Volume up"),
        ("vol_down", "🔉", "Volume down"),
        ("show_volume", "🎚️", "Show volume dialog"),
        ("cycle_ringer", "🔔", "Cycle ringer mode (Ring, Vibrate, Silent)"),
        ("toggle_dnd", "⛔", "Toggle Do Not Disturb"),
        ("mute", "🔇", "Mute volume"),
        ("unmute", "🔈", "Unmute volume"),
        ("toggle_mute", "🔕", "Toggle mute"),
    ],
    "Apps": [
        ("voice_assistant", "✨", "Launch voice assistant"),
        ("camera", "📷", "Open camera"),
        ("settings", "⚙️", "Open settings"),
    ],
    "Navigation": [
        ("notif_drawer", "🔽", "Toggle notification drawer"),
        ("quick_settings", "🎛️", "Toggle quick settings drawer"),
        ("back", "◀️", "Go back"),
        ("home", "🏠", "Go home"),
    ],
}

# --------------------------------------------------------------------------- model reliability note
RELIABILITY_NOTE = (
    "Prototype / simulation. The bundled baseline model (CSP + SVM, Left vs Right) is close to "
    "chance level, so helmet decisions must never be used to drive a real wheelchair."
)
