import pytest
import uuid

from calm.dsl.cli.main import get_api_client
from calm.dsl.cli.constants import RUNLOG
from tests.api_interface.test_runbooks.test_files.exec_task import (EscriptTask,
                                                                    SetVariableOnEscript,
                                                                    EscriptOnEndpoint)
from utils import upload_runbook, poll_runlog_status


class TestExecTasks:
    @pytest.mark.slown
    @pytest.mark.parametrize('Runbook', [EscriptTask, SetVariableOnEscript, EscriptOnEndpoint])
    def test_script_run(self, Runbook):
        """ test_access_set_variable_in_next_task, test_escript_task,
            test_script_type_escript_execute_task_on_endpoint_with_multiple_ips"""

        client = get_api_client()
        rb_name = "test_exectask_" + str(uuid.uuid4())[-10:]

        rb = upload_runbook(client, rb_name, Runbook)
        rb_state = rb["status"]["state"]
        rb_uuid = rb["metadata"]["uuid"]
        print(">> Runbook state: {}".format(rb_state))
        assert rb_state == "ACTIVE"
        assert rb_name == rb["spec"]["name"]
        assert rb_name == rb["metadata"]["name"]

        # endpoints generated by this runbook
        endpoint_list = rb['spec']['resources'].get('endpoint_definition_list', [])

        # running the runbook
        print("\n>>Running the runbook")

        res, err = client.runbook.run(rb_uuid, {})
        if err:
            pytest.fail("[{}] - {}".format(err["code"], err["error"]))

        response = res.json()
        runlog_uuid = response["status"]["runlog_uuid"]

        # polling till runbook run gets to terminal state
        state, reasons = poll_runlog_status(client, runlog_uuid, RUNLOG.TERMINAL_STATES)

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
            if entity["status"]["type"] == "task_runlog" and\
                    entity["status"]["task_reference"]["name"] == "ExecTask" and\
                    entity["status"].get("machine_name", "") != "-":
                exec_tasks.append(entity["metadata"]["uuid"])

        # Now checking the output of exec task
        for exec_task in exec_tasks:
            res, err = client.runbook.runlog_output(runlog_uuid, exec_task)
            if err:
                pytest.fail("[{}] - {}".format(err["code"], err["error"]))
            runlog_output = res.json()
            output_list = runlog_output['status']['output_list']
            assert output_list[0]['output'] == 'Task is Successful\n'

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
