import time
import click
import arrow
import json
import sys
import uuid
from prettytable import PrettyTable

from calm.dsl.api import get_api_client, get_resource_api
from calm.dsl.config import get_config
from calm.dsl.log import get_logging_handle
from calm.dsl.store import Cache
from calm.dsl.builtins import Ref

from .constants import ACP
from .utils import get_name_query, highlight_text


LOG = get_logging_handle(__name__)


def get_acps(name, project_name, filter_by, limit, offset, quiet, out):
    """ Get the acps, optionally filtered by a string """

    client = get_api_client()
    config = get_config()

    # TODO remove this internal call by projects api
    project_cache_data = Cache.get_entity_data(entity_type="project", name=project_name)
    if not project_cache_data:
        LOG.error(
            "Project {} not found. Please run: calm update cache".format(project_name)
        )
        sys.exit(-1)

    project_uuid = project_cache_data["uuid"]

    params = {"length": limit, "offset": offset}
    filter_query = ""
    if name:
        filter_query = get_name_query([name])
    if filter_by:
        filter_query = filter_query + ";(" + filter_by + ")"
    if project_uuid:
        filter_query = filter_query + ";(project_reference=={})".format(project_uuid)
    if filter_query.startswith(";"):
        filter_query = filter_query[1:]

    if filter_query:
        params["filter"] = filter_query

    res, err = client.acp.list(params=params)

    if err:
        pc_ip = config["SERVER"]["pc_ip"]
        LOG.warning("Cannot fetch acps from {}".format(pc_ip))
        return

    if out == "json":
        click.echo(json.dumps(res.json(), indent=4, separators=(",", ": ")))
        return

    json_rows = res.json()["entities"]
    if not json_rows:
        click.echo(highlight_text("No acp found !!!\n"))
        return

    if quiet:
        for _row in json_rows:
            row = _row["status"]
            click.echo(highlight_text(row["name"]))
        return

    table = PrettyTable()
    table.field_names = [
        "NAME",
        "STATE",
        "REFERENCED_ROLE",
        "REFERENCED_PROJECT",
        "UUID",
    ]

    for _row in json_rows:
        row = _row["status"]
        metadata = _row["metadata"]

        role_ref = row["resources"].get("role_reference", {})
        role = role_ref.get("name", "-")

        table.add_row(
            [
                highlight_text(row["name"]),
                highlight_text(row["state"]),
                highlight_text(role),
                highlight_text(project_name),
                highlight_text(metadata["uuid"]),
            ]
        )

    click.echo(table)


def get_system_roles():

    # 'Self-Service Admin', 'Prism Admin', 'Prism Viewer', 'Super Admin' are forbidden roles
    return ["Project Admin", "Operator", "Consumer", "Developer"]


def create_acp(role, project, user, group, name):

    client = get_api_client()
    acp_name = name or "nuCalmAcp-{}".format(str(uuid.uuid4()))

    # Check whether there is an existing acp with this name
    params = {"filter": "name=={}".format(acp_name)}
    res, err = client.acp.list(params=params)
    if err:
        return None, err

    response = res.json()
    entities = response.get("entities", None)

    if entities:
        LOG.error("ACP {} already exists.".format(acp_name))
        sys.exit(-1)

    # TODO remove this internal call by projects api
    project_cache_data = Cache.get_entity_data(entity_type="project", name=project)
    if not project_cache_data:
        LOG.error("Project {} not found. Please run: calm update cache".format(project))
        sys.exit(-1)

    project_uuid = project_cache_data["uuid"]
    whitelisted_subnets = project_cache_data["whitelisted_subnets"]

    cluster_uuids = []
    for subnet_uuid in whitelisted_subnets:
        subnet_cache_data = Cache.get_entity_data_using_uuid(
            entity_type="ahv_subnet", uuid=subnet_uuid
        )

        cluster_uuids.append(subnet_cache_data["cluster_uuid"])

    role_cache_data = Cache.get_entity_data(entity_type="role", name=role)
    role_uuid = role_cache_data["uuid"]

    # Check if there is an existing acp with given (project-role) tuple
    params = {
        "length": 1000,
        "filter": "role_uuid=={};project_reference=={}".format(role_uuid, project_uuid),
    }
    res, err = client.acp.list(params)
    if err:
        return None, err

    response = res.json()
    entities = response.get("entities", None)

    if entities:
        LOG.error(
            "ACP {} already exists for given role in project".format(
                entities[0]["status"]["name"]
            )
        )
        sys.exit(-1)

    # Creating filters for acp
    default_context = ACP.DEFAULT_CONTEXT

    # Setting project uuid in default context
    default_context["scope_filter_expression_list"][0]["right_hand_side"][
        "uuid_list"
    ] = [project_uuid]

    # Role specific filters
    entity_filter_expression_list = []
    if role == "Project Admin":
        entity_filter_expression_list = (
            ACP.ENTITY_FILTER_EXPRESSION_LIST.PROJECT_ADMIN
        )  # TODO remove index bases searching
        entity_filter_expression_list[4]["right_hand_side"]["uuid_list"] = [
            project_uuid
        ]

    elif role == "Developer":
        entity_filter_expression_list = ACP.ENTITY_FILTER_EXPRESSION_LIST.DEVELOPER

    elif role == "Consumer":
        entity_filter_expression_list = ACP.ENTITY_FILTER_EXPRESSION_LIST.CONSUMER

    elif role == "Operator" and cluster_uuids:
        entity_filter_expression_list = ACP.ENTITY_FILTER_EXPRESSION_LIST.CONSUMER

    if cluster_uuids:
        entity_filter_expression_list.append(
            {
                "operator": "IN",
                "left_hand_side": {"entity_type": "cluster",},
                "right_hand_side": {"uuid_list": cluster_uuids,},
            }
        )

    # TODO check these users are not present in project's other acps
    user_references = []
    for u in user:
        user_references.append(Ref.User(u))

    group_references = []
    for g in group:
        group_references.append(Ref.Group(g))

    context_list = [default_context]
    if entity_filter_expression_list:
        context_list.append(
            {"entity_filter_expression_list": entity_filter_expression_list}
        )

    acp_payload = {
        "acp": {
            "name": acp_name,
            "resources": {
                "role_reference": Ref.Role(role),
                "user_reference_list": user_references,
                "user_group_reference_list": group_references,
                "filter_list": {"context_list": context_list},
            },
        },
        "metadata": {"kind": "access_control_policy",},
        "operation": "ADD",
    }

    # Getting the project_internal payload
    ProjectInternalObj = get_resource_api("projects_internal", client.connection)
    res, err = ProjectInternalObj.read(project_uuid)
    if err:
        LOG.error(err)
        sys.exit(-1)

    project_payload = res.json()
    project_payload.pop("status", None)

    # Appending acp payload to project
    project_payload["spec"]["access_control_policy_list"].append(acp_payload)

    res, err = ProjectInternalObj.update(project_uuid, project_payload)
    if err:
        LOG.error(err)
        sys.exit(-1)

    res = res.json()
    stdout_dict = {
        "name": acp_name,
        "execution_context": res["status"]["execution_context"],
    }
    click.echo(json.dumps(stdout_dict, indent=4, separators=(",", ": ")))


def delete_acp(acp_name, project_name):

    client = get_api_client()

    # TODO remove this internal call by projects api
    project_cache_data = Cache.get_entity_data(entity_type="project", name=project_name)
    if not project_cache_data:
        LOG.error(
            "Project {} not found. Please run: calm update cache".format(project_name)
        )
        sys.exit(-1)

    project_uuid = project_cache_data["uuid"]

    LOG.info("Fetching project '{}' details".format(project_name))
    Obj = get_resource_api("projects_internal", client.connection)
    res, err = Obj.read(project_uuid)
    if err:
        LOG.error(err)
        sys.exit(-1)

    project_payload = res.json()
    project_payload.pop("status", None)

    for _row in project_payload["spec"].get("access_control_policy_list", []):
        if _row["acp"]["name"] == acp_name:
            _row["operation"] = "DELETE"
        else:
            _row["operation"] = "UPDATE"

    LOG.info(
        "Deleting acp '{}' associated with project '{}'".format(acp_name, project_name)
    )
    res, err = client.project.update(project_uuid, project_payload)
    if err:
        LOG.error(err)
        sys.exit(-1)

    res = res.json()
    stdout_dict = {
        "name": acp_name,
        "execution_context": res["status"]["execution_context"],
    }
    click.echo(json.dumps(stdout_dict, indent=4, separators=(",", ": ")))


def update_acp(
    acp_name,
    project_name,
    add_user_list,
    add_group_list,
    remove_user_list,
    remove_group_list,
):

    client = get_api_client()

    # TODO remove this internal call by projects api
    project_cache_data = Cache.get_entity_data(entity_type="project", name=project_name)
    if not project_cache_data:
        LOG.error(
            "Project {} not found. Please run: calm update cache".format(project_name)
        )
        sys.exit(-1)

    project_uuid = project_cache_data["uuid"]

    LOG.info("Fetching project '{}' details".format(project_name))
    Obj = get_resource_api("projects_internal", client.connection)
    res, err = Obj.read(project_uuid)
    if err:
        LOG.error(err)
        sys.exit(-1)

    project_payload = res.json()
    project_payload.pop("status", None)

    # Raise error if same user/group is present in both add/remove list
    common_users = set(add_user_list).intersection(set(remove_user_list))
    if common_users:
        LOG.error("Users {} are both in add_user and remove_user".format(common_users))
        sys.exit(-1)

    common_groups = set(add_group_list).intersection(set(remove_group_list))
    if common_groups:
        LOG.error(
            "Groups {} are present both in add_groups and remove_groups".format(
                common_groups
            )
        )
        sys.exit(-1)

    # Flag to checvk whether given acp is present in project or not
    is_acp_present = False
    for _row in project_payload["spec"].get("access_control_policy_list", []):
        _row["operation"] = "UPDATE"

        if _row["acp"]["name"] == acp_name:
            is_acp_present = True
            acp_resources = _row["acp"]["resources"]
            updated_user_reference_list = []
            updated_group_reference_list = []

            for user in acp_resources.get("user_reference_list", []):
                if user["name"] not in remove_user_list:
                    updated_user_reference_list.append(user)

            for group in acp_resources.get("user_group_reference_list", []):
                if group["name"] not in remove_group_list:
                    updated_group_reference_list.append(group)

            for user in add_user_list:
                updated_user_reference_list.append(Ref.User(user))

            for group in add_group_list:
                updated_group_reference_list.append(Ref.Group(group))

            acp_resources["user_reference_list"] = updated_user_reference_list
            acp_resources["user_group_reference_list"] = updated_group_reference_list

    if not is_acp_present:
        LOG.error(
            "No ACP with name '{}' exists in project '{}'".format(
                acp_name, project_name
            )
        )
        sys.exit(-1)

    LOG.info(
        "Updating acp '{}' associated with project '{}'".format(acp_name, project_name)
    )
    res, err = client.project.update(project_uuid, project_payload)
    if err:
        LOG.error(err)
        sys.exit(-1)

    res = res.json()
    stdout_dict = {
        "name": acp_name,
        "execution_context": res["status"]["execution_context"],
    }
    click.echo(json.dumps(stdout_dict, indent=4, separators=(",", ": ")))
