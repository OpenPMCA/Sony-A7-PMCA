import runpy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class GuiSummaryTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.gui = runpy.run_path(str(Path(__file__).resolve().parents[1]/'pmca-gui.py'))['main'].__globals__

 def test_missing_camera_information_clears_stale_fields(self):
  variables = {'Model': Mock(), 'Firmware version': Mock()}
  frame = SimpleNamespace(infoVars=variables, infoStatus=Mock())
  self.gui['InfoFrame'].showCameraInfo(frame, None)
  for value in variables.values():
   value.set.assert_called_with('—')
  self.assertIn('Could not read', frame.infoStatus.set.call_args.args[0])

 def test_camera_summary_displays_only_reported_values(self):
  variables = {'Model': Mock(), 'Firmware version': Mock(), 'Lens': Mock()}
  frame = SimpleNamespace(infoVars=variables, infoStatus=Mock())
  self.gui['InfoFrame'].showCameraInfo(frame, {'Model':'ILCE-7','Firmware version':'3.20'})
  variables['Model'].set.assert_called_with('ILCE-7')
  variables['Firmware version'].set.assert_called_with('3.20')
  variables['Lens'].set.assert_called_with('—')

 def test_install_failure_stops_progress_without_marking_one_hundred_percent(self):
  class Bar(dict):
   def stop(self): pass
   def config(self, **kwargs): pass
  bar = Bar(value=35)
  frame = SimpleNamespace(progressBar=bar, progressText=Mock())
  self.gui['InstallerFrame'].showInstallResult(frame, False)
  self.assertEqual(bar['value'],35)
  self.assertIn('did not complete',frame.progressText.set.call_args.args[0])


if __name__ == '__main__':
 unittest.main()
