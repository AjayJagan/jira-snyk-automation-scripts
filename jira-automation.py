import json
import logging
import os
import re
import snyk
import sys

from jira import JIRA
from dataclasses import dataclass
from datetime import datetime, timedelta
from dotenv import load_dotenv

VULNERABILITY_SEVERITIES = ["critical", "high"]


class SnykClient:
    __client: snyk.SnykClient

    def __init__(self, snyk_api_token: str):
        try:
            self.__client = snyk.SnykClient(
                snyk_api_token, tries=2, delay=1, backoff=2)
        except SystemError:
            logging.error("failed to create snyk client")
            sys.exit(1)

    def get_organization(self, org_id: str) -> {}:
        """
        returns snyk org object

        :param org_id: snyk organization id
        :return: snyk organization object
        """
        return self.__client.organizations.get(org_id)


class JiraClient:
    __client: JIRA
    __jira_label_prefix: str
    __jira_project_id: str
    __jira_component_list: []
    __dry_run: bool

    def __init__(
            self,
            jira_server: str,
            jira_api_token: str,
            jira_label_prefix: str,
            jira_project_id: str,
            jira_component_list: [],
            dry_run: bool):
        try:
            self.__jira_component_list = jira_component_list
            self.__jira_label_prefix = jira_label_prefix
            self.__jira_project_id = jira_project_id
            self.__dry_run = dry_run
            self.__client = JIRA(
                options={
                    "server": jira_server,
                    "verify": True},
                token_auth=jira_api_token)
        except SystemError:
            logging.error("failed to create jira client")
            sys.exit(1)

    def is_dry_run(self) -> bool:
        """
        returns if it is dry run. Jira issues will not be created if true

        :return: dry run
        """
        return self.__dry_run

    def get_project_id(self) -> str:
        """
        returns jira project id. In this project all bugs will be created

        :return: jira project id
        """
        return self.__jira_project_id

    def get_component_list(self) -> []:
        """
        returns the list of components
        """
        return self.__jira_component_list

    def get_jira_label_prefix(self) -> str:
        """
        returns jira label prefix. All created bugs have special label created by this script,
        so this script can identify, which bugs it should load.

        :return: jira label prefix
        """
        return self.__jira_label_prefix

    def get_component_dict_list(self, component):
        return {"name": component}
    
    def create_jira_issues(
            self,
            vulnerabilities_to_create: [],
            jira_project_id: str,
            snyk_project_id: str,
            snyk_org_slug: str,
            jira_epic_id: str):
        """
        creates new jira bugs from given list of vulnerabilities

        :param vulnerabilities_to_create: list of vulnerabilities to create
        :param jira_project_id: jira project id where all bugs will be created
        :param snyk_project_id: id of snyk project
        :param snyk_org_slug: name of snyk organization (e.g. red-hat-openshift-virtualisation)
        """
        jira_issues_to_create = []
        for vulnerability in vulnerabilities_to_create:
            jira_issue = {"project": jira_project_id,
                          "summary": vulnerability.get_jira_summary(),
                          "description": vulnerability.get_jira_description(
                              snyk_org_slug,
                              snyk_project_id),
                          "components": list(map(self.get_component_dict_list, vulnerability.get_component_list())),
                          "duedate": vulnerability.calculate_due_date(),
                          "issuetype": {'name': 'Bug'},
                          "labels": [vulnerability.get_jira_snyk_id()]}

            jira_issues_to_create.append(jira_issue)
        if not self.is_dry_run():
            try:
                created_jira_issues = self.__client.create_issues(
                    jira_issues_to_create)
                issue_keys = []
                for issue in created_jira_issues:
                    for key in issue:
                        issue_keys.append(key)
                self.__client.add_issues_to_epic(jira_epic_id, issue_keys)
                for issue in created_jira_issues:
                    logging.info(
                        f"Created JIRA issue key: {issue['issue']}")
                logging.info(
                        f"Added to the epic: {jira_epic_id['jira_epic_id']}")
            except SystemError:
                logging.error("failed to create jira issues")
        else:
            print(f"dry run. No issues created. ({len(jira_issues_to_create)} issues would be created)")

    def list_existing_jira_issues(
            self,
            jira_query: str,
            start_at: int,
            max_results: int) -> ([], bool):
        """
        list all jira bugs with given JQL query

        :param jira_query: JQL query, which loads already existing jira bugs
        :param start_at: position, where jira should start looking for new issues - used for pagination
        :param max_results: number of results jira should return
        :return: list of jira bugs, boolean, if there are any more results
        """
        issues = self.__client.search_issues(
            jql_str=jira_query,
            startAt=start_at,
            maxResults=max_results)
        return issues, False


@dataclass
class VulnerabilityData:
    __id: str
    __jira_snyk_id: str
    __title: str
    __url: str
    __project_branch: str
    __package_name: str
    __package_version: []
    __fixed_in: []
    __project_name: str
    __file_path: str
    __component_list: []
    __severity: str
    __cvss_score: float
    __identifiers: {}

    def __init__(
            self,
            snyk_id: str,
            jira_snyk_id: str,
            title: str,
            url: str,
            project_branch: str,
            package_name: str,
            package_version: [],
            fixed_in: [],
            project_name: str,
            file_name: str,
            component_list: [],
            cvss_score: float,
            identifiers: {},
            severity: str):
        self.__id = snyk_id
        self.__jira_snyk_id = jira_snyk_id
        self.__title = title
        self.__url = url
        self.__project_branch = project_branch
        self.__package_name = package_name
        self.__package_version = package_version
        self.__fixed_in = fixed_in
        self.__project_name = project_name
        self.__file_path = file_name
        self.__component_list = component_list
        self.__cvss_score = cvss_score
        self.__identifiers = identifiers
        self.__severity = severity

    def get_id(self):
        """
        returns snyk ID of vulnerability e.g. SNYK-UBUNTU1404-OPENSSL-2426359

        :return: snyk ID
        """
        return self.__id

    def get_jira_snyk_id(self):
        """
        returns jira ID, in format: snyk-jira-integration:<gh org>/<gh repo name>:<file path>:<branch name>:<snyk ID>
        e.g. snyk-jira-integration:kubevirt/kubevirt-tekton-tasks:modules/generate-ssh-keys/vendor/golang.org/x/net/http2/Dockerfile:main:SNYK-UBUNTU1404-OPENSSL-2426359
        The ID is so long, because snyk does not provide any unique ID for vulnerability - so e.g. 2 projects
        can have vulnerability with the same id. To be able to map vulnerabilities to snyk, we need to capture
        multiple information like GH project name, file path, branch name, snyk id ...
        possible optimalization - create hash from this long string id

        :return: jira-snyk id
        """

        return self.__jira_snyk_id

    def get_title(self) -> str:
        """
        returns jira bug title

        :return: jira bug title
        """

        return self.__title

    def get_url(self) -> str:
        """
        returns url to snyk system which describes vulnerability

        :return: url to snyk system
        """

        return self.__url

    def get_package_name(self) -> str:
        """
        returns golang package name where vulnerability is

        :return: golang package name
        """

        return self.__package_name

    def get_identifiers(self) -> {}:
        """
        returns CVE, CWE identifiers

        :return: dict identifiers
        """

        return self.__identifiers

    def get_cvss_score(self) -> float:
        """
        returns cvss score

        :return: cvss score
        """

        return self.__cvss_score

    def get_package_version(self) -> []:
        """
        returns versions which are affected by vulnerability

        :return: package version
        """

        return self.__package_version

    def get_fixed_in(self) -> []:
        """
        returns versions in which vulnerability is fixed

        :return: package version
        """

        return self.__fixed_in

    def get_project_name(self) -> str:
        """
        returns <gh org name>/<project name> name, where snyk found vulnerability

        :return: returns project name
        """

        return self.__project_name

    def get_file_path(self) -> str:
        """
        returns file path, where snyk found vulnerability

        :return: returns file path
        """

        return self.__file_path

    def get_component_list(self) -> []:
        """
        returns jira component list

        :return: returns jira component list
        """

        return self.__component_list

    def get_severity(self) -> str:
        """
        returns severity of vulnerability

        :return: returns severity of vulnerability
        """

        return self.__severity

    def get_project_branch(self) -> str:
        """
        returns branch name where the vulnerability was found

        :return: returns branch name
        """

        return self.__project_branch

    def get_jira_description(
            self,
            snyk_org_slug: str,
            snyk_project_id: str) -> str:
        """
        returns jira description of the bug

        :param snyk_project_id: id of snyk project
        :param snyk_org_slug: name of snyk organization (e.g. red-hat-openshift-virtualisation)
        :return: returns jira description of bug
        """
        cve = self.get_identifiers().get("CVE")
        return f"Found vulnerability in *{self.get_project_name()}* project, in file *{self.get_file_path()}*, " \
            f"in branch *{self.get_project_branch()}*. \n\n" \
            f"Severity: {self.get_severity()}. \n\n" \
            f"Package name: {self.get_package_name()} \n\n" \
            f"Package version: {self.get_package_version()} \n\n" \
            f"Fixed in: {self.get_fixed_in()} \n\n" \
            f"Vulnerability URL: {self.get_url()}. \n\n" \
            f"CSSV score: {self.get_cvss_score()}. \n\n" \
            f"CVE Identifier: {cve}. \n\n" \
            f"More info can be found in https://app.snyk.io/org/{snyk_org_slug}/project/{snyk_project_id}#issue-{self.get_id()}. \n"

    def get_jira_summary(self) -> str:
        cve = self.get_identifiers().get("CVE")
        summary = "Snyk - "
        if cve:
             summary += f"[{cve[0]}] - "

        return summary + f"[{self.get_severity()}] - [{self.get_project_branch()}] - {self.get_project_name()} - " \
            f"{self.get_file_path()} - {self.get_title()}"

    def calculate_due_date(self) -> str:
        number_of_days = 30
        if self.get_severity() == "critical":
            number_of_days = 7
        return (
            datetime.today() +
            timedelta(
                days=number_of_days)).strftime('%Y-%m-%d')


def list_snyk_vulnerabilities(
        vulnerabilities: [],
        project_branch: str,
        project_name: str,
        file_name: str,
        jira_client: JiraClient) -> ([], str):
    patchable_vulnerabilities = []
    jira_query = f"project={jira_client.get_project_id()} AND ("
    for vulnerability in vulnerabilities:
            jira_snyk_id = f"{jira_client.get_jira_label_prefix()}{project_name}:{file_name}:{project_branch}:{vulnerability.id}"
            vulnerability_obj = VulnerabilityData(
                snyk_id=vulnerability.id,
                jira_snyk_id=jira_snyk_id,
                title=vulnerability.issueData.title,
                url=vulnerability.issueData.url,
                package_name=vulnerability.pkgName,
                package_version=vulnerability.pkgVersions,
                fixed_in=vulnerability.fixInfo.fixedIn,
                project_name=project_name,
                project_branch=project_branch,
                file_name=file_name,
                component_list=jira_client.get_component_list(),
                cvss_score=vulnerability.issueData.cvssScore,
                identifiers=vulnerability.issueData.identifiers,
                severity=vulnerability.issueData.severity)
            patchable_vulnerabilities.append(vulnerability_obj)

            jira_query += f" labels=\"{jira_snyk_id}\" OR"
    # remove last OR operand from query
    jira_query = jira_query[:-2] + ")"
    return patchable_vulnerabilities, jira_query


def compare_jira_snyk(
        vulnerabilities: [],
        jira_issues: [],
        jira_label_prefix: str) -> []:
    jira_issue_labels = set()
    for issue in jira_issues:
        for label in issue.fields.labels:
            if label.startswith(jira_label_prefix):
                jira_issue_labels.add(label)
    return [v for v in vulnerabilities if v.get_jira_snyk_id()
            not in jira_issue_labels]


def parse_project_name(project_name: str, branch_name: str) -> str:
    return project_name.partition(":")[0].removesuffix(f"({branch_name})")


def parse_file_name(project_name: str) -> str:
    return project_name.partition(":")[2]


def exclude_file(file_name: str, excluded_files: dict) -> bool:
    for excluded_file in excluded_files:
        if re.search(excluded_file, file_name):
            return True
    return False


def process_projects(
        jira_client: JiraClient,
        project: any,
        exclude_files: dict,
        jira_epic_id:str):
        project_name = parse_project_name(project.name, project.branch)
        file_name = parse_file_name(project.name)
        excluded_files = exclude_files.get(project_name, None)
        if excluded_files and exclude_file(file_name, excluded_files):
            logging.info(
                f"skipping file {file_name}, because of the record in exclude_file.json")
        issue_set = project.issueset_aggregated.all()
        if issue_set.issues:
            logging.info(
                f"looking for vulnerabilities in: {project_name}, file: {file_name}, branch: {project.branch}")
            vulnerabilities_to_compare_list, jira_query = list_snyk_vulnerabilities(
                issue_set.issues, project.branch, project_name, file_name, jira_client)
            if vulnerabilities_to_compare_list:
                process_vulnerabilities(
                    jira_client,
                    vulnerabilities_to_compare_list,
                    jira_query,
                    project.id,
                    project.organization.slug,
                    jira_epic_id)
                
def process_vulnerabilities(
        jira_client: JiraClient,
        vulnerabilities_to_compare_list: [],
        jira_query: str,
        project_id: str,
        snyk_org_slug: str,
        jira_epic_id: str):
    load_more = True
    start_at = 0
    max_results = 50
    while load_more:
        # TODO fix paging functions
        jira_issues, load_more = jira_client.list_existing_jira_issues(
            jira_query, start_at, max_results)
        vulnerabilities_to_create_list = compare_jira_snyk(
            vulnerabilities_to_compare_list,
            jira_issues,
            jira_client.get_jira_label_prefix())
        if vulnerabilities_to_create_list:
            jira_client.create_jira_issues(
                vulnerabilities_to_create_list,
                jira_client.get_project_id(),
                project_id,
                snyk_org_slug,
                jira_epic_id
                )
            start_at += max_results


def load_mapping(file_path: str) -> {}:
    try:
        os.path.isfile(file_path)
    except SystemError:
        logging.error("the file does not exists")
        sys.exit(1)

    component_maping = {}
    try:
        with open(file_path) as f:
            data = f.read()
            component_maping = json.loads(data)
    except SystemError:
        logging.error("failed to load file")
        sys.exit(1)
    return component_maping


def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    exclude_files_file_path = os.environ.get("EXCLUDE_FILES_FILE_PATH") if os.environ.get(
        "EXCLUDE_FILES_FILE_PATH") else "exclude_files.json"
    exclude_files_mapping = load_mapping(
        exclude_files_file_path)
    # These env vars can be stored in a GH secret.
    snyk_api_token = os.environ.get("SNYK_API_TOKEN")
    logging.info(snyk_api_token)
    if not snyk_api_token:
        logging.error("SNYK_API_TOKEN env variable not defined")
        sys.exit(2)
    jira_api_token = os.environ.get("JIRA_API_TOKEN")
    logging.info(jira_api_token)
    if not jira_api_token:
        logging.error("JIRA_API_TOKEN env variable not defined")
        sys.exit(2)
    # These variables are read from the .env file
    snyk_org_id =os.environ.get("SNYK_ORG_ID")
    logging.info(snyk_org_id)
    if not snyk_org_id:
        logging.error("SNYK_ORG_ID env variable not defined")
        sys.exit(2)
    jira_server =os.environ.get("JIRA_SERVER")
    logging.info(jira_server)
    if not jira_server:
        logging.error("JIRA_SERVER env variable not defined")
        sys.exit(2)
    jira_project_id =os.environ.get("JIRA_PROJECT_ID")
    logging.info(jira_project_id)
    if not jira_project_id:
        logging.error("JIRA_PROJECT_ID env variable not defined")
        sys.exit(2)

    jira_label_prefix =os.environ.get("JIRA_LABEL_PREFIX") if os.environ.get(
        "JIRA_LABEL_PREFIX") else "snyk-jira-integration:"
    
    jira_component_list =os.environ.get("JIRA_COMPONENT_NAMES")
    logging.info(jira_component_list)
    if not jira_component_list:
        logging.error("JIRA_COMPONENT_NAMES not defined")
        sys.exit(2)

    jira_epic_id =os.environ.get("JIRA_EPIC_ID")
    logging.info(jira_epic_id)
    if not jira_epic_id:
        logging.error("JIRA_PROJECT_ID env variable not defined")
        sys.exit(2)

    snyk_project_id =os.environ.get("SNYK_PROJECT_ID")
    logging.info(snyk_project_id)
    if not snyk_project_id:
        logging.error("SNYK_PROJECT_ID env variable not defined")
        sys.exit(2)

    dry_run =os.environ.get("DRY_RUN")
    if dry_run:
        logging.info("DRY_RUN is enabled")

    snyk_client = SnykClient(snyk_api_token)
    snyk_org = snyk_client.get_organization(snyk_org_id)
    project = snyk_org.projects.get(snyk_project_id)
    jira_client = JiraClient(
        jira_server,
        jira_api_token,
        jira_label_prefix,
        jira_project_id,
        jira_component_list.split(","),
        dry_run)
    process_projects(jira_client, project, exclude_files_mapping,jira_epic_id)


if __name__ == "__main__":
    main()
