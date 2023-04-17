import pytest
import uuid
import json

from distutils.version import LooseVersion as LV
from calm.dsl.builtins import read_local_file
from calm.dsl.store import Version
from calm.dsl.config import get_context
from calm.dsl.cli.main import get_api_client
from calm.dsl.cli.constants import RUNLOG
from calm.dsl.log import get_logging_handle
from utils import upload_runbook, poll_runlog_status

LOG = get_logging_handle(__name__)
DSL_CONFIG = json.loads(read_local_file(".tests/config.json"))
DSL_CONFIG = json.loads(read_local_file(".tests/config.json"))

# calm_version
CALM_VERSION = Version.get_version("Calm")


@pytest.mark.skipif(
    LV(CALM_VERSION) < LV("3.5.0") or not DSL_CONFIG.get("IS_VPC_ENABLED", False),
    reason="VPC Tunnels can be used in Calm v3.5.0+ or VPC is disabled on the setup",
)
class TestExecTasksVMEndpoint:
    def teardown_method(self):
        ContextObj = get_context()
        ContextObj.reset_configuration()

    @pytest.mark.runbook
    @pytest.mark.regression
    def test_script_run_linux(self):
        from tests.api_interface.test_runbooks.test_files.exec_task import (
            ShellTaskinVpc,
        )

        client = get_api_client()
        rb_name = "test_exectask_vm_ep_" + str(uuid.uuid4())[-10:]

        rb = upload_runbook(client, rb_name, ShellTaskinVpc)
        rb_state = rb["status"]["state"]
        rb_uuid = rb["metadata"]["uuid"]
        print(">> Runbook state: {}".format(rb_state))
        assert rb_state == "ACTIVE"
        assert rb_name == rb["spec"]["name"]
        assert rb_name == rb["metadata"]["name"]

        # endpoints generated by this runbook
        endpoint_list = rb["spec"]["resources"].get("endpoint_definition_list", [])

        # running the runbook
        print("\n>>Running the runbook")

        res, err = client.runbook.run(rb_uuid, {})
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))

        response = res.json()
        runlog_uuid = response["status"]["runlog_uuid"]

        # polling till runbook run gets to terminal state
        state, reasons = poll_runlog_status(
            client, runlog_uuid, RUNLOG.TERMINAL_STATES, maxWait=360
        )

        print(">> Runbook Run state: {}\n{}".format(state, reasons))
        assert state == RUNLOG.STATUS.SUCCESS

        # Finding the trl id for the exec task (all runlogs for multiple IPs)
        exec_tasks = []
        res, err = client.runbook.list_runlogs(runlog_uuid)
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))
        response = res.json()
        entities = response["entities"]
        for entity in entities:
            if (
                entity["status"]["type"] == "task_runlog"
                and entity["status"]["task_reference"]["name"] == "ExecTask"
                and runlog_uuid in entity["status"].get("machine_name", "")
            ):
                exec_tasks.append(entity["metadata"]["uuid"])

        # Now checking the output of exec task
        for exec_task in exec_tasks:
            res, err = client.runbook.runlog_output(runlog_uuid, exec_task)
            if err:
                pytest.fail("[{}] - {}".format(err["code"], err["error"]))
            runlog_output = res.json()
            output_list = runlog_output["status"]["output_list"]
            assert "Task is Successful" in output_list[0]["output"]

        # delete the runbook
        _, err = client.runbook.delete(rb_uuid)
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))
        else:
            print("runbook {} deleted".format(rb_name))

        # delete endpoints generated by this test
        for endpoint in endpoint_list:
            _, err = client.endpoint.delete(endpoint["uuid"])
            if err:
                pytest.fail("[{}] - {}".format(err["code"], err["error"]))

    @pytest.mark.runbook
    @pytest.mark.regression
    def test_script_run_windows(self):
        from tests.api_interface.test_runbooks.test_files.exec_task import (
            PowershellTaskinVpc,
        )

        client = get_api_client()
        rb_name = "test_exectask_vm_ep_" + str(uuid.uuid4())[-10:]

        rb = upload_runbook(client, rb_name, PowershellTaskinVpc)
        rb_state = rb["status"]["state"]
        rb_uuid = rb["metadata"]["uuid"]
        print(">> Runbook state: {}".format(rb_state))
        assert rb_state == "ACTIVE"
        assert rb_name == rb["spec"]["name"]
        assert rb_name == rb["metadata"]["name"]

        # endpoints generated by this runbook
        endpoint_list = rb["spec"]["resources"].get("endpoint_definition_list", [])

        # running the runbook
        print("\n>>Running the runbook")

        res, err = client.runbook.run(rb_uuid, {})
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))

        response = res.json()
        runlog_uuid = response["status"]["runlog_uuid"]

        # polling till runbook run gets to terminal state
        state, reasons = poll_runlog_status(
            client, runlog_uuid, RUNLOG.TERMINAL_STATES, maxWait=360
        )

        print(">> Runbook Run state: {}\n{}".format(state, reasons))
        assert state == RUNLOG.STATUS.SUCCESS

        # Finding the trl id for the exec task (all runlogs for multiple IPs)
        exec_tasks = []
        res, err = client.runbook.list_runlogs(runlog_uuid)
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))
        response = res.json()
        entities = response["entities"]
        for entity in entities:
            if (
                entity["status"]["type"] == "task_runlog"
                and entity["status"]["task_reference"]["name"] == "ExecTask"
                and runlog_uuid in entity["status"].get("machine_name", "")
            ):
                exec_tasks.append(entity["metadata"]["uuid"])

        # Now checking the output of exec task
        for exec_task in exec_tasks:
            res, err = client.runbook.runlog_output(runlog_uuid, exec_task)
            if err:
                pytest.fail("[{}] - {}".format(err["code"], err["error"]))
            runlog_output = res.json()
            output_list = runlog_output["status"]["output_list"]
            assert "Task is Successful" in output_list[0]["output"]

        # delete the runbook
        _, err = client.runbook.delete(rb_uuid)
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))
        else:
            print("runbook {} deleted".format(rb_name))

        # delete endpoints generated by this test
        for endpoint in endpoint_list:
            _, err = client.endpoint.delete(endpoint["uuid"])
            if err:
                pytest.fail("[{}] - {}".format(err["code"], err["error"]))