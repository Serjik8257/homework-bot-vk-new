"""Проверки обработки некорректных данных и сбоев отправки в VK."""

import logging
from unittest.mock import Mock, call

import pytest
import requests
import vk_api

import homework


class StopBot(BaseException):
    """Останавливает тестовый цикл без ожидания десяти минут."""


@pytest.fixture
def bot_dependencies(monkeypatch):
    """Подменяет сеть и запускает не более двух итераций бота."""
    for name, value in (
        ('PRACTICUM_TOKEN', 'test-practicum-token'),
        ('VK_TOKEN', 'test-vk-token'),
        ('VK_USER_ID', '12345'),
    ):
        monkeypatch.setattr(homework, name, value)
    vk = Mock()
    session = Mock()
    session.get_api.return_value = vk
    monkeypatch.setattr(homework.vk_api, 'VkApi', Mock(return_value=session))
    monkeypatch.setattr(homework, 'configure_logging', Mock())
    monkeypatch.setattr(homework.time, 'time', Mock(return_value=100))

    response = {
        'homeworks': [{'homework_name': 'Test project', 'status': 'approved'}],
        'current_date': 200,
    }
    get_answer = Mock(return_value=response)
    monkeypatch.setattr(homework, 'get_api_answer', get_answer)
    sleep = Mock(side_effect=[None, StopBot()])
    monkeypatch.setattr(homework.time, 'sleep', sleep)
    monkeypatch.setattr(
        requests.sessions.Session, 'request',
        Mock(side_effect=AssertionError('Сетевые запросы в тестах запрещены')),
    )
    return vk, get_answer, sleep, response


@pytest.mark.parametrize('data, error_type, detail', [
    ({}, KeyError, 'homework_name'),
    ({'homework_name': 'Test project'}, KeyError, 'status'),
    ([], TypeError, 'словарём'),
    ({'homework_name': 'Test project', 'status': []}, TypeError, 'строкой'),
    (
        {'homework_name': 'Test project', 'status': 'unknown'},
        ValueError, 'unknown',
    ),
])
def test_invalid_homework_has_specific_error(data, error_type, detail):
    """Ошибка объясняет, какое именно поле или значение некорректно."""
    with pytest.raises(error_type, match=detail):
        homework.parse_status(data)


@pytest.mark.parametrize('error_type', [
    vk_api.exceptions.VkApiError,
    requests.exceptions.ReadTimeout,
    RuntimeError,
])
def test_vk_failure_is_logged_once_and_bot_continues(
    bot_dependencies, caplog, error_type,
):
    """После сбоя бот не отправляет ошибку в VK и продолжает опрос."""
    vk, get_answer, sleep, _ = bot_dependencies
    vk.messages.send.side_effect = [error_type('test VK failure'), None]

    with caplog.at_level(logging.ERROR), pytest.raises(StopBot):
        homework.main()

    assert get_answer.call_count == 2
    assert sleep.call_args_list == [call(homework.RETRY_PERIOD)] * 2
    assert vk.messages.send.call_count == 2
    for sent in vk.messages.send.call_args_list:
        assert sent.kwargs['message'].startswith('Изменился статус')
    errors = [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ]
    assert len(errors) == 1
    assert 'test VK failure' in errors[0].getMessage()


def test_failed_error_notification_does_not_stop_bot(bot_dependencies, caplog):
    """Сбой VK во время уведомления об ошибке API не прерывает цикл."""
    vk, get_answer, sleep, response = bot_dependencies
    get_answer.side_effect = [ConnectionError('test API failure'), response]
    vk.messages.send.side_effect = [
        requests.ReadTimeout('test VK timeout'), None,
    ]

    with caplog.at_level(logging.ERROR), pytest.raises(StopBot):
        homework.main()

    assert get_answer.call_args_list == [call(100), call(100)]
    assert sleep.call_count == 2
    assert vk.messages.send.call_count == 2
    first_message = vk.messages.send.call_args_list[0].kwargs['message']
    second_message = vk.messages.send.call_args_list[1].kwargs['message']
    assert 'test API failure' in first_message
    assert second_message.startswith('Изменился статус')
    assert 'test VK timeout' in caplog.text


def test_empty_response_does_not_repeat_previous_message(bot_dependencies):
    """Пустой ответ на следующем опросе не дублирует уведомление."""
    vk, get_answer, _, response = bot_dependencies
    get_answer.side_effect = [response, {'homeworks': [], 'current_date': 300}]

    with pytest.raises(StopBot):
        homework.main()

    assert get_answer.call_args_list == [call(100), call(200)]
    assert vk.messages.send.call_count == 1


def test_invalid_date_keeps_timestamp_without_vk_notification(
    bot_dependencies,
):
    """Ответ без временной метки не отправляется в VK и не меняет отсчёт."""
    vk, get_answer, _, response = bot_dependencies
    get_answer.side_effect = [
        {'homeworks': response['homeworks']}, response,
    ]

    with pytest.raises(StopBot):
        homework.main()

    assert get_answer.call_args_list == [call(100), call(100)]
    assert vk.messages.send.call_count == 1
