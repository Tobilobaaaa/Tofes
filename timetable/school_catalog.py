"""Shared subject list and staff allocations for seed and sync commands."""

from timetable.models import ClassLevel, Section

JUNIOR_SUBJECTS = [
    ('ENG', 'English', 4),
    ('BSC', 'Basic Science', 3),
    ('FRE', 'French', 1),
    ('MTH', 'Mathematics', 4),
    ('SOS', 'Social Studies', 2),
    ('YOR', 'Yoruba', 2),
    ('BTE', 'Basic Technology', 2),
    ('CRSJ', 'CRS / IRS', 2),
    ('CCA', 'CCA', 2),
    ('BST', 'Business Studies', 2),
    ('AGRJ', 'Agric Science', 2),
    ('CIVJ', 'Civic Education', 2),
    ('PHE', 'Physical and Health Edu', 2),
    ('HEC', 'Home Economics', 2),
    ('ICT', 'ICT', 2),
]

SENIOR_STANDALONE = [
    ('ENGS', 'English', 4),
    ('AGRS', 'Agric Science', 3),
    ('LVST', 'Livestock', 2),
    ('MTHS', 'Mathematics', 4),
    ('CIVS', 'Civic Education', 3),
    ('ECO', 'Economics', 3),
    ('MKT', 'Marketing', 3),
    ('GOVT', 'Government', 4),
]

# (code, name, group name, periods)
SENIOR_SIMULTANEOUS = [
    ('CHEM', 'Chemistry', 'Chemistry / Commerce / CRS', 4),
    ('COM', 'Commerce', 'Chemistry / Commerce / CRS', 4),
    ('CRSS', 'CRS', 'Chemistry / Commerce / CRS', 4),
    ('PHY', 'Physics', 'Physics / Accounting / Literature', 4),
    ('ACC', 'Accounting', 'Physics / Accounting / Literature', 4),
    ('LIT', 'Literature', 'Physics / Accounting / Literature', 3),
    ('BIO', 'Biology', 'Biology / Yoruba', 3),
    ('YORS', 'Yoruba', 'Biology / Yoruba', 3),
]

TEACHER_SUBJECTS = [
    ('Mrs Ogunnaike', 'ENG', Section.JUNIOR),
    ('Mrs Ogunnaike', 'ENGS', Section.SENIOR),
    ('Mrs Ogunnaike', 'LIT', Section.SENIOR),
    ('Mr Sunday', 'MTH', Section.JUNIOR),
    ('Mr Sunday', 'MTHS', Section.SENIOR),
    ('Mr Sunday', 'PHY', Section.SENIOR),
    ('Mr Godwin', 'GOVT', Section.SENIOR),
    ('Mr Godwin', 'BTE', Section.JUNIOR),
    ('Mr Godwin', 'CCA', Section.JUNIOR),
    ('Mr Oyediran', 'ACC', Section.SENIOR),
    ('Mr Oyediran', 'COM', Section.SENIOR),
    ('Mr Prince', 'CHEM', Section.SENIOR),
    ('Mr Prince', 'BIO', Section.SENIOR),
    ('Mr Prince', 'ICT', Section.JUNIOR),
    ('Mrs Adeniyi', 'SOS', Section.JUNIOR),
    ('Mrs Adeniyi', 'CRSJ', Section.JUNIOR),
    ('Mrs Adeniyi', 'CRSS', Section.SENIOR),
    ('Mrs Adeniyi', 'HEC', Section.JUNIOR),
    ('Mrs Mesioye', 'AGRJ', Section.JUNIOR),
    ('Mrs Mesioye', 'AGRS', Section.SENIOR),
    ('Mrs Mesioye', 'LVST', Section.SENIOR),
    ('Mrs Mesioye', 'YOR', Section.JUNIOR),
    ('Mrs Mesioye', 'YORS', Section.SENIOR),
    ('Mr Victor', 'PHE', Section.JUNIOR),
    ('Mr Victor', 'BSC', Section.JUNIOR),
    ('Mr Victor', 'CIVJ', Section.JUNIOR),
    ('Mr Victor', 'CIVS', Section.SENIOR),
    ('Mr Michael', 'ECO', Section.SENIOR),
    ('Mr Michael', 'MKT', Section.SENIOR),
    ('Mrs Adewale', 'FRE', Section.JUNIOR),
]

TEACHER_NOTES = {
    'Mrs Ogunnaike': 'English and Literature',
    'Mr Sunday': 'Mathematics and Physics',
    'Mr Godwin': 'Government, B.Tech and CCA',
    'Mr Oyediran': 'Accounting, Commerce and JSS 3 Business Studies',
    'Mr Prince': 'Chemistry, Biology and ICT',
    'Mrs Adeniyi': 'Social Studies, CRS and Home Economics',
    'Mrs Mesioye': 'Agric, Livestock and Yoruba',
    'Mr Victor': 'PHE, Basic Science and Civic',
    'Mr Michael': 'Economics, Marketing and JSS 1–2 Business Studies',
    'Mrs Adewale': 'French',
}

CLASS_OVERRIDES = {
    (ClassLevel.JSS1, 'BST'): 'Mr Michael',
    (ClassLevel.JSS2, 'BST'): 'Mr Michael',
    (ClassLevel.JSS3, 'BST'): 'Mr Oyediran',
}

JUNIOR_LEVELS = {ClassLevel.JSS1, ClassLevel.JSS2, ClassLevel.JSS3}
