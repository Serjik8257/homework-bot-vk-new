import logging
import os
import time
from http import HTTPStatus

import requests
import vk_api
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
VK_TOKEN = os.getenv('VK_TOKEN')
VK_USER_ID = os.getenv('VK_USER_ID')

RETRY_PERIOD = 600
REQUEST_TIMEOUT = 15
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


class InvalidCurrentDateError(ValueError):
    """Ошибка, если API не вернул корректную временную метку."""


def check_tokens():
    """Проверяет, что все необходимые переменные окружения заданы."""
    token_names = ('PRACTICUM_TOKEN', 'VK_TOKEN', 'VK_USER_ID')
    missing_tokens = [
        name for name in token_names if not globals()[name]
    ]
    if missing_tokens:
        logger.critical(
            'Не заданы обязательные переменные окружения: %s.',
            ', '.join(missing_tokens)
        )
        return False
    return True


def configure_logging():
    """Настраивает логирование при запуске, а не при импорте модуля."""
    logging.basicConfig(
        level=logging.DEBUG,
        format=(
            '%(asctime)s [%(levelname)s] %(funcName)s:%(lineno)d '
            '%(message)s'
        )
    )


def send_message(vk, message):
    """Отправляет сообщение пользователю ВКонтакте."""
    try:
        vk.messages.send(
            user_id=int(VK_USER_ID),
            message=message,
            random_id=0
        )
    except (vk_api.exceptions.VkApiError, requests.RequestException) as error:
        logger.exception('Не удалось отправить сообщение в VK: %s', error)
    else:
        logger.debug('Успешно отправлено сообщение в VK: %s', message)


def get_api_answer(timestamp):
    """Запрашивает статусы домашних работ у API Практикума."""
    params = {'from_date': timestamp}

    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT
        )
        if response.status_code != HTTPStatus.OK:
            raise ConnectionError(
                f'API вернуло статус {response.status_code}'
            )
        return response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise ValueError('API вернуло некорректный JSON.') from error
    except requests.RequestException as error:
        raise ConnectionError(
            f'Не удалось запросить API: {error}'
        ) from error


def check_response(response):
    """Проверяет структуру ответа API."""
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарём.')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ homeworks.')

    if not isinstance(response['homeworks'], list):
        raise TypeError('Значение homeworks должно быть списком.')

    current_date = response.get('current_date')
    if not isinstance(current_date, int):
        raise InvalidCurrentDateError(
            'В ответе API отсутствует корректная временная метка current_date.'
        )


def parse_status(homework):
    """Формирует сообщение об изменении статуса домашней работы."""
    try:
        homework_name = homework['homework_name']
        status = homework['status']
        verdict = HOMEWORK_VERDICTS[status]
    except (KeyError, TypeError) as error:
        raise ValueError(
            'В ответе API отсутствуют нужные данные '
            'или получен неизвестный статус: '
            f'{error}'
        ) from error

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    configure_logging()

    if not check_tokens():
        raise SystemExit('Проверьте настройки в файле .env.')

    # Создаем сессию для бота
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    timestamp = int(time.time())

    logger.info('Бот запущен.')

    while True:
        sending_message = False
        try:
            response = get_api_answer(timestamp)
            check_response(response)

            if response['homeworks']:
                homework = response['homeworks'][-1]
                message = parse_status(homework)
                sending_message = True
                send_message(vk, message)
                sending_message = False
            else:
                logger.debug('Новых статусов домашних работ нет.')

            timestamp = response['current_date']

        except InvalidCurrentDateError as error:
            logger.error('%s Сохраняем прежнюю временную метку.', error)
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.exception(message)
            if not sending_message:
                send_message(vk, message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
