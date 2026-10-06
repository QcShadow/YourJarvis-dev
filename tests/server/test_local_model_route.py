from openjarvis.server.routes import _obvious_mode


def test_obvious_work_stays_on_agent_path():
    assert _obvious_mode('打开浏览器') == 'tool'
    assert _obvious_mode('Read my desktop file') == 'tool'
    assert _obvious_mode('现在几点') == 'tool'
    assert _obvious_mode('我打算去武汉，武汉有什么好玩的') == 'tool'
    assert _obvious_mode('Things to do in Wuhan') == 'tool'


def test_obvious_greeting_uses_fast_chat_path():
    assert _obvious_mode('你好') == 'chat'
    assert _obvious_mode('Hello') == 'chat'


def test_ambiguous_request_is_left_to_small_model():
    assert _obvious_mode('请解释一下量子纠缠的实验与常见误解') is None


def test_obvious_deep_reasoning_uses_stronger_model():
    assert _obvious_mode('请深入分析两种系统架构的取舍') == 'deep'
