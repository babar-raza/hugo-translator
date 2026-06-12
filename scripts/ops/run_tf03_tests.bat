@echo off
call C:\Users\prora\anaconda3\Scripts\activate.bat hugo-translator
cd /d c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
python -m pytest tests/unit/phase-5/test_engine.py -k "test_translate_with_tm_hit or test_translate_force_bypass_tm or test_accept_on_first_try or test_retry_on_validation_failure or test_reject_after_max_retries or test_feedback_applied_to_retry_prompt or test_validation_disabled_no_retry or test_retry_feedback_prepended_to_text or test_no_feedback_on_first_attempt or test_temperature_variation_logged or test_temperature_maxes_out" -v
