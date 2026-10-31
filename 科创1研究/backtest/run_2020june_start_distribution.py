"""科创基准1：2020年6月逐交易日起点敏感性回放。"""
from pathlib import Path
import run_2020q1_start_distribution as job

job.OUT=job.STAR/'results/start_dates_2020june_to_20260930'
job.WINDOW_START='2020-06-01'
job.WINDOW_END='2020-06-30'

if __name__=='__main__':job.main()
