@echo off
cd /d "c:\Docker\dayLog"
if not exist "data\daily" mkdir "data\daily"
python -m app
