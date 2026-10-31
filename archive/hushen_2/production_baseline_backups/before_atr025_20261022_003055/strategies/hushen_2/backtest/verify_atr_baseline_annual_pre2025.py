"""Independent original-version annual replay checks, same checks as ATR025."""
import inspect
import verify_atr025_annual_pre2025 as prior


def main():
    source=inspect.getsource(prior.main)
    assert source.count('atr_ge_025')==1
    source=source.replace('atr_ge_025','original')
    exec(compile(source,'<verify_original_annual_pre2025>','exec'),prior.__dict__)
    prior.main()


if __name__=='__main__':main()
