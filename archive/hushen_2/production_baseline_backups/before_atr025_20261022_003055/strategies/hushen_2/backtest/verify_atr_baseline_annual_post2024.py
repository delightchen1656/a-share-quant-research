"""Independent controls verification using unchanged saved-curve verifier."""
import inspect
import verify_atr025_annual_post2024 as prior

def main():
    source=inspect.getsource(prior.main)
    prior.__dict__.update(__file__=__file__)
    exec(compile(source,'<baseline_independent_saved_curve_verifier>','exec'),prior.__dict__)
    prior.main()

if __name__=='__main__':main()
