# Snyk - Jira integration
Script, which loads all snyk vulnerabilities and creates Bugs in jira.

## Getting started
1. Clone repo
2. Export the necessary variables - SNYK_API_TOKEN, JIRA_API_TOKEN
3. Update the .env with the all necessary values.
4. In case you need to exclude folders, insert regex in exclude_files.json in format:
{
    "kubevirt/kubevirt-tekton-tasks": {
        "^modules/.*/vendor": ""
    },
    "<GH org>/<repo name>": {
        "path_regex": "<empty_string>"
    }
}
5. export all these env variables:
    ```
    # https://docs.snyk.io/snyk-cli/authenticate-the-cli-with-your-account
    export SNYK_API_TOKEN=""
    export JIRA_API_TOKEN="""
    ```
1. run script `python jira-automation.py`
2. script will go through all snyk vulnerabilities and create Jira bugs