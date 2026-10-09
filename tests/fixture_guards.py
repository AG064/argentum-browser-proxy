from contextlib import contextmanager, ExitStack
from unittest.mock import patch


@contextmanager
def unit_guards():
    # Source/UI units use mocked transports; the container suite tests enforcement.
    with ExitStack() as stack:
        stack.enter_context(patch('deployment_access.enforce_request', return_value=None))
        stack.enter_context(patch('fetch_tickets.sign', return_value='f'*64))
        stack.enter_context(patch('isolation_runtime.require_isolation', return_value={'proxy':'http://fixture.invalid:3128'}))
        stack.enter_context(patch('isolation_runtime.guarded_command', side_effect=lambda command,seconds:command))
        stack.enter_context(patch('isolation_runtime.ffmpeg_options', side_effect=lambda command,cookies=None:command))
        yield
