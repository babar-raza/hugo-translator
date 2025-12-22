# Model Registry CT2 Path Verification

## Summary
Updated config/model_registry.yaml with local_path entries for CT2 models.

## Changes Made

### 1. Added local_path to existing CT2 model:
- m2m100_418m_ct2: ./models/ct2/m2m100_418m

### 2. Added new INT8 model entries:
- m2m100_418m_ct2_int8: ./models/ct2/m2m100_418m_int8
- nllb_200_600m_ct2_int8: ./models/ct2/nllb_200_600m_int8

## Model Count
- Before: 10 models (1 CT2 without local_path)
- After: 12 models (3 CT2 models with local_path)

## CT2 Models in Registry
1. m2m100_418m_ct2 (FP32) - 800MB, 2GB RAM
2. m2m100_418m_ct2_int8 (INT8) - 250MB, 1.5GB RAM
3. nllb_200_600m_ct2_int8 (INT8) - 350MB, 2GB RAM

## Path Verification Status
Note: The model paths point to ./models/ct2/* directories that will be created
during CPU-01 conversions. These paths are specified correctly and will exist
after the conversion process is completed.

Expected paths after CPU-01 completion:
- ./models/ct2/m2m100_418m/
- ./models/ct2/m2m100_418m_int8/
- ./models/ct2/nllb_200_600m_int8/

## YAML Validation
The YAML file is syntactically valid and follows the existing registry format.
All new entries maintain consistency with existing model specifications.

## Backup Created
Backup file: config/model_registry.yaml.backup

