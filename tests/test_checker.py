import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facet.bpmn.checker import BPMN, MAX_BYTES, check_bytes, check_file, write_html


def document(body):
    return f'<definitions xmlns="{BPMN}" targetNamespace="urn:test"><process id="p">{body}</process></definitions>'.encode()


def codes(body):
    return {issue.code for issue in check_bytes(document(body)).issues}


class CheckerTests(unittest.TestCase):
    def test_message_flows_require_two_pools_and_valid_endpoints(self):
        def collaboration(source='send', target='receive', process_ref='seller', kind_target='task'):
            return f'''<definitions xmlns="{BPMN}" targetNamespace="urn:test">
                <process id="buyer"><task id="send" name="Отправить"/><task id="same" name="В том же пуле"/></process>
                <process id="seller"><{kind_target} id="receive" name="Получить"/></process>
                <collaboration id="collab"><participant id="a" processRef="buyer"/>
                    <participant id="b" processRef="{process_ref}"/>
                    <messageFlow id="message" sourceRef="{source}" targetRef="{target}"/>
                </collaboration></definitions>'''.encode()
        def issues(data): return {issue.code for issue in check_bytes(data).issues}
        self.assertEqual(issues(collaboration()),set())
        self.assertIn('MESSAGE_FLOW_SAME_POOL',issues(collaboration(target='same')))
        self.assertIn('MESSAGE_FLOW_REFERENCE',issues(collaboration(target='missing')))
        self.assertIn('MESSAGE_FLOW_POOL',issues(collaboration(process_ref='missing')))
        self.assertIn('PARTICIPANT_PROCESS',issues(collaboration(process_ref='missing')))
        self.assertIn('MESSAGE_FLOW_ENDPOINT',issues(collaboration(kind_target='exclusiveGateway')))
        self.assertIn('MESSAGE_FLOW_SCOPE',issues(document('<task id="a" name="A"/><messageFlow id="m" sourceRef="a" targetRef="a"/>')))

    def test_valid_process(self):
        self.assertFalse(check_bytes(document('''
            <startEvent id="s"/><task id="t" name="Проверить"/><endEvent id="e"/>
            <sequenceFlow id="a" sourceRef="s" targetRef="t"/>
            <sequenceFlow id="b" sourceRef="t" targetRef="e"/>
        ''')).issues)

    def test_implicit_start_end_are_legal(self):
        self.assertEqual(codes('<task id="a" name="Первый"/><task id="b" name="Второй"/><sequenceFlow id="f" sourceRef="a" targetRef="b"/>'), set())

    def test_broken_reference_does_not_cascade(self):
        self.assertEqual(codes('<startEvent id="s"/><endEvent id="e"/><sequenceFlow id="f" sourceRef="s" targetRef="missing"/>'), {"BROKEN_REFERENCE"})

    def test_flow_in_empty_process_is_checked(self):
        self.assertIn("BROKEN_REFERENCE", codes('<sequenceFlow id="f" sourceRef="missing" targetRef="gone"/>'))

    def test_illegal_event_directions(self):
        found = codes('<startEvent id="s"/><endEvent id="e"/><sequenceFlow id="f" sourceRef="e" targetRef="s"/>')
        self.assertTrue({"START_INCOMING", "END_OUTGOING"} <= found)

    def test_unreachable_cycle(self):
        found = codes('''<startEvent id="s"/><endEvent id="e"/>
            <task id="x" name="Забытый"/><sequenceFlow id="f" sourceRef="s" targetRef="e"/>
            <sequenceFlow id="loop" sourceRef="x" targetRef="x"/>''')
        self.assertIn("UNREACHABLE", found)

    def test_cycle_with_exit_is_not_a_dead_end(self):
        found = codes('''<startEvent id="s"/><task id="t" name="Шаг"/><endEvent id="e"/>
            <sequenceFlow id="a" sourceRef="s" targetRef="t"/>
            <sequenceFlow id="b" sourceRef="t" targetRef="t"/>
            <sequenceFlow id="c" sourceRef="t" targetRef="e"/>''')
        self.assertNotIn("NO_PATH_TO_END", found)

    def test_reachable_trap(self):
        found = codes('''<startEvent id="s"/><task id="t" name="Шаг"/>
            <sequenceFlow id="a" sourceRef="s" targetRef="t"/>
            <sequenceFlow id="b" sourceRef="t" targetRef="t"/>''')
        self.assertIn("NO_PATH_TO_END", found)

    def test_nested_process_has_separate_graph(self):
        found = codes('''<startEvent id="s"/><subProcess id="sub" name="Обработать">
            <startEvent id="inner_s"/><endEvent id="inner_e"/>
            <sequenceFlow id="inner_f" sourceRef="inner_s" targetRef="inner_e"/>
            </subProcess><endEvent id="e"/>
            <sequenceFlow id="a" sourceRef="s" targetRef="sub"/>
            <sequenceFlow id="b" sourceRef="sub" targetRef="e"/>''')
        self.assertEqual(found, set())

    def test_cross_scope_flow(self):
        found = codes('''<task id="a" name="Шаг"/><subProcess id="sub" name="Вложенный">
            <task id="b" name="Внутри"/></subProcess>
            <sequenceFlow id="f" sourceRef="a" targetRef="b"/>''')
        self.assertIn("BROKEN_REFERENCE", found)

    def test_boundary_event_is_reachable_through_activity(self):
        found = codes('''<startEvent id="s"/><task id="t" name="Шаг"/>
            <boundaryEvent id="b" attachedToRef="t"><timerEventDefinition/></boundaryEvent>
            <endEvent id="e"/><endEvent id="timeout"/>
            <sequenceFlow id="a" sourceRef="s" targetRef="t"/>
            <sequenceFlow id="c" sourceRef="t" targetRef="e"/>
            <sequenceFlow id="d" sourceRef="b" targetRef="timeout"/>''')
        self.assertNotIn("UNREACHABLE", found)
        self.assertIn("PATH_CHECK_LIMITED", found)

    def test_bad_boundary_attachment(self):
        self.assertIn("BOUNDARY_ATTACHMENT", codes('<boundaryEvent id="b" attachedToRef="missing"/>'))

    def test_duplicate_and_missing_id(self):
        self.assertIn("DUPLICATE_ID", codes('<task id="same"/><task id="same"/>'))
        self.assertIn("MISSING_ID", codes('<task name="Без ID"/>'))

    def test_conditions_and_default(self):
        found = codes('''<exclusiveGateway id="g" default="fallback"/><endEvent id="a"/><endEvent id="b"/>
            <sequenceFlow id="f" sourceRef="g" targetRef="a"><conditionExpression>x &gt; 0</conditionExpression></sequenceFlow>
            <sequenceFlow id="fallback" sourceRef="g" targetRef="b"/>''')
        self.assertNotIn("BRANCH_CONDITION", found)
        self.assertNotIn("INVALID_DEFAULT", found)
        self.assertIn("INVALID_DEFAULT", codes('<task id="t" name="Шаг" default="missing"/>'))

    def test_unconditional_branches_are_advice(self):
        report = check_bytes(document('''<exclusiveGateway id="g"/><endEvent id="a"/><endEvent id="b"/>
            <sequenceFlow id="f" name="Да" sourceRef="g" targetRef="a"/>
            <sequenceFlow id="j" name="Нет" sourceRef="g" targetRef="b"/>'''))
        self.assertEqual(report.errors, 0)
        self.assertEqual(sum(issue.code == "BRANCH_CONDITION" for issue in report.issues), 2)

    def test_event_subprocess_is_not_reported_unreachable(self):
        found = codes('''<startEvent id="s"/><endEvent id="e"/>
            <sequenceFlow id="f" sourceRef="s" targetRef="e"/>
            <subProcess id="sub" name="По событию" triggeredByEvent="true">
            <startEvent id="ss"><messageEventDefinition id="trigger"/></startEvent><endEvent id="ee"/>
            <sequenceFlow id="ff" sourceRef="ss" targetRef="ee"/></subProcess>''')
        self.assertNotIn("UNREACHABLE", found)
        self.assertIn("ADVANCED_SCOPE", found)

    def test_event_subprocess_requires_single_triggered_start_and_no_external_flow(self):
        base = '<subProcess id="sub" name="По событию" triggeredByEvent="true">{}</subProcess>'
        self.assertIn("EVENT_SUBPROCESS_START_COUNT", codes(base.format('<endEvent id="e"/>')))
        self.assertIn("EVENT_SUBPROCESS_START_COUNT", codes(base.format(
            '<startEvent id="a"/><startEvent id="b"/>')))
        self.assertIn("EVENT_SUBPROCESS_TRIGGER", codes(base.format('<startEvent id="a"/>')))
        valid = '<startEvent id="a"><signalEventDefinition id="signal"/></startEvent>'
        self.assertNotIn("EVENT_SUBPROCESS_TRIGGER", codes(base.format(valid)))
        self.assertIn("EVENT_SUBPROCESS_FLOW", codes(
            '<task id="t" name="Работа"/>' + base.format(valid) +
            '<sequenceFlow id="f" sourceRef="t" targetRef="sub"/>'))

    def test_event_gateway_requires_valid_exclusive_waits(self):
        base = '''<eventBasedGateway id="g"/>
            <intermediateCatchEvent id="message"><messageEventDefinition id="m"/></intermediateCatchEvent>
            <intermediateCatchEvent id="timer"><timerEventDefinition id="t"/></intermediateCatchEvent>
            <sequenceFlow id="gm" sourceRef="g" targetRef="message"/>
            <sequenceFlow id="gt" sourceRef="g" targetRef="timer"/>'''
        invalid_codes = {"EVENT_GATEWAY_BRANCHES", "EVENT_GATEWAY_CONDITION",
                         "EVENT_GATEWAY_TARGET", "EVENT_GATEWAY_TARGET_INCOMING",
                         "EVENT_GATEWAY_TRIGGER", "EVENT_GATEWAY_MIXED_MESSAGE"}
        self.assertFalse(codes(base) & invalid_codes)
        self.assertIn("EVENT_GATEWAY_BRANCHES", codes('<eventBasedGateway id="g"/>'))
        self.assertIn("EVENT_GATEWAY_CONDITION", codes(base.replace(
            'sourceRef="g" targetRef="timer"/>',
            'sourceRef="g" targetRef="timer"><conditionExpression>true</conditionExpression></sequenceFlow>')))
        self.assertIn("EVENT_GATEWAY_TARGET", codes(base.replace('targetRef="timer"', 'targetRef="other"') +
                                                    '<task id="other" name="Действие"/>'))
        self.assertIn("EVENT_GATEWAY_TARGET_INCOMING", codes(base +
            '<task id="other" name="Действие"/><sequenceFlow id="extra" sourceRef="other" targetRef="timer"/>'))
        self.assertIn("EVENT_GATEWAY_TRIGGER", codes(base.replace('timerEventDefinition', 'linkEventDefinition')))
        mixed = base.replace('<intermediateCatchEvent id="timer"><timerEventDefinition id="t"/></intermediateCatchEvent>',
                             '<receiveTask id="timer" name="Получить"/>')
        self.assertIn("EVENT_GATEWAY_MIXED_MESSAGE", codes(mixed))
        self.assertIn("EVENT_GATEWAY_PARALLEL_INSTANTIATE", codes(base.replace(
            '<eventBasedGateway id="g"/>', '<eventBasedGateway id="g" eventGatewayType="Parallel"/>')))
        self.assertIn("EVENT_GATEWAY_INSTANTIATE_INCOMING", codes(base.replace(
            '<eventBasedGateway id="g"/>', '<eventBasedGateway id="g" instantiate="true"/>') +
            '<task id="before" name="До"/><sequenceFlow id="before-g" sourceRef="before" targetRef="g"/>'))

    def test_multi_instance_requires_count_or_collection(self):
        task='<userTask id="t" name="Проверить"><multiInstanceLoopCharacteristics>{}</multiInstanceLoopCharacteristics></userTask>'
        self.assertIn('MULTI_INSTANCE_COUNT', codes(task.format('')))
        self.assertIn('MULTI_INSTANCE_COUNT', codes(task.format('<loopCardinality>-2</loopCardinality>')))
        self.assertNotIn('MULTI_INSTANCE_COUNT', codes(task.format('<loopCardinality>3</loopCardinality>')))
        self.assertNotIn('MULTI_INSTANCE_COUNT', codes(task.format('<loopDataInputRef>items</loopDataInputRef>')))

    def test_receive_task_start_rejects_incoming_flow(self):
        receive='<receiveTask id="receive" name="Получить" instantiate="true"/>'
        self.assertNotIn('RECEIVE_INSTANTIATE_INCOMING', codes(receive))
        self.assertIn('RECEIVE_INSTANTIATE_INCOMING', codes(receive+
            '<task id="before" name="До"/><sequenceFlow id="flow" sourceRef="before" targetRef="receive"/>'))

    def test_malformed_xml_and_entities(self):
        for data in (b"broken", b'<!DOCTYPE x [<!ENTITY a "a">]><x/>', '<x/>'.encode("utf-16")):
            with self.subTest(data=data):
                self.assertEqual(check_bytes(data).issues[0].code, "INVALID_XML")

    def test_other_xml_is_not_bpmn(self):
        self.assertEqual(check_bytes(b"<definitions/>").issues[0].code, "NOT_BPMN")

    def test_size_limit(self):
        self.assertEqual(check_bytes(b"x" * (MAX_BYTES + 1)).issues[0].code, "FILE_TOO_LARGE")

    def test_html_escapes_names(self):
        report = check_bytes(document('<task id="t" name="&lt;script&gt;alert(1)&lt;/script&gt;" default="bad"/>'), '<img src=x>')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.html"
            write_html(report, path)
            content = path.read_text()
            self.assertNotIn("<script>", content)
            self.assertNotIn("<img src=x>", content)
            self.assertIn("&lt;script&gt;", content)

    def test_cli_and_exit_status(self):
        checker = Path(__file__).resolve().parents[1] / "checker.py"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "test.bpmn"
            source.write_bytes(document('<endEvent id="e"/><startEvent id="s"/><sequenceFlow id="f" sourceRef="e" targetRef="s"/>'))
            result = subprocess.run([sys.executable, str(checker), str(source), "--json"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertGreater(json.loads(result.stdout)["errors"], 0)
            before = source.read_bytes()
            result = subprocess.run([sys.executable, str(checker), str(source), "--html", str(source)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(source.read_bytes(), before)

    def test_missing_file(self):
        self.assertEqual(check_file("/does-not-exist/process.bpmn").issues[0].code, "FILE_READ")


if __name__ == "__main__":
    unittest.main()
