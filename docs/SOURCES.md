# Implementation references

Primary documentation consulted for the selected stack and verification workflow:

- [Streamlit app testing](https://docs.streamlit.io/develop/api-reference/app-testing)
- [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
- [scikit-learn IsolationForest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)

The repository pins its tested environment, including Streamlit 1.50.0 and scikit-learn 1.7.2;
current documentation may describe newer versions. Installed signatures and executable tests verified
the APIs actually used. None of these references supplies real automotive thresholds or procedures.

CI action versions were checked against the official repositories: [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), [upload-artifact](https://github.com/actions/upload-artifact).
