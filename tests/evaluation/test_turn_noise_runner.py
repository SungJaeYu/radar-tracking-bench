"""Turn replay records changing angles without changing the fixed-scenario recorder."""
import csv
import math
import json
import pytest
from pc_sim.simulation.prepared_input import InputSettings, generate_input
from pc_sim.evaluation.turn_noise import TurnRecorder, position_metrics, run


def test_turn_recorder_preserves_truth_and_wire_measurement(tmp_path):
    settings = InputSettings(scenario='straight_turn_straight', duration_s=80, dt_s=.1)
    data = generate_input(settings)
    path = tmp_path / 'recording'
    with TurnRecorder(path, settings, 'board') as recorder:
        for sample in (data.samples[0], data.samples[-1]):
            recorder.record_sample(sample, 123.0)
    with (path/'samples.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['truth_azimuth_rad'] != rows[1]['truth_azimuth_rad']
    assert float(rows[1]['truth_azimuth_rad']) == data.samples[-1].truth_azimuth_rad
    assert float(rows[1]['measured_azimuth_rad']) == data.samples[-1].wire_azimuth_sc * math.pi/2**31
    assert bytes.fromhex(rows[1]['frame_hex']) == data.samples[-1].frame
    with (path/'reports.csv').open('a') as stream:
        writer = csv.writer(stream)
        for index in (0, 20, 110, 700):
            s=data.samples[index]
            writer.writerow([index,s.timestamp_ms,s.timestamp_ms,s.truth_range_m,s.truth_azimuth_rad,0,0,2,0 if index == 0 else 1,3,123])
    metrics = position_metrics(path,data)
    assert metrics['all']['count'] == 3
    assert metrics['all']['rmse_m'] < 1e-10
    assert all(metrics[key]['count'] == 1 for key in ('straight_before','turn','straight_after'))


def test_failed_serial_open_retains_incomplete_recording(tmp_path):
    with pytest.raises(OSError):
        run('/nonexistent/radar-port', tmp_path)
    path, = tmp_path.iterdir()
    metadata=json.loads((path/'metadata.json').read_text())
    assert metadata['complete'] is False
    assert metadata['closed'] is True
    assert (path/'input'/'metadata.json').exists()


def test_position_warmup_restarts_on_reacquisition(tmp_path):
    settings=InputSettings(scenario='straight_turn_straight',duration_s=80,dt_s=.1)
    data=generate_input(settings)
    path=tmp_path/'session'
    with TurnRecorder(path,settings,'board'):
        pass
    with (path/'reports.csv').open('a') as stream:
        writer=csv.writer(stream)
        for index,result in ((0,0),(20,1),(100,0),(110,1),(120,1)):
            s=data.samples[index]
            writer.writerow([index,s.timestamp_ms,s.timestamp_ms,s.truth_range_m,s.truth_azimuth_rad,0,0,2,result,3,123])
    metrics=position_metrics(path,data)
    assert metrics['all']['count']==2
    assert metrics['straight_before']['count']==1
    assert metrics['turn']['count']==1


def test_midrun_exception_preserves_partial_files(tmp_path, monkeypatch):
    class BrokenSerial:
        def __enter__(self):
            return self
        def __exit__(self,*args):
            self.closed=True
        def write(self,frame):
            raise OSError('injected write failure')
    connection=BrokenSerial()
    monkeypatch.setattr('pc_sim.evaluation.turn_noise.serial.Serial',lambda *a,**kw:connection)
    with pytest.raises(OSError,match='injected'):
        run('fake',tmp_path)
    path,=tmp_path.iterdir()
    assert connection.closed
    assert json.loads((path/'metadata.json').read_text())['complete'] is False
    assert (path/'wire.csv').exists()


def test_noise_overrides_are_saved_before_uart_open(tmp_path):
    with pytest.raises(OSError):
        run('/nonexistent/radar-port',tmp_path,noise=3,azimuth_noise=.002)
    path,=tmp_path.iterdir()
    from pc_sim.storage.prepared_storage import load_input
    metadata=load_input(path/'input').metadata
    assert metadata['settings']['range_noise_std_m']==3
    assert metadata['settings']['azimuth_noise_std_rad']==.002


def test_saved_input_cannot_be_silently_changed(tmp_path):
    with pytest.raises(ValueError,match='already defines noise'):
        run('fake',tmp_path,input_directory=tmp_path/'input',noise=2)
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('value',[-1,float('nan'),float('inf')])
def test_invalid_noise_fails_before_files_or_uart(tmp_path,value):
    with pytest.raises(ValueError):
        run('fake',tmp_path,noise=value)
    assert list(tmp_path.iterdir())==[]
