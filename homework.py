import logging
import os
import time

import requests
import vk_api
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
VK_TOKEN = os.getenv('VK_TOKEN')
VK_USER_ID = os.getenv('VK_USER_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def check_tokens():
    """Проверяет, что все необходимые переменные окружения заданы."""
    return all([PRACTICUM_TOKEN, VK_TOKEN, VK_USER_ID])


def send_message(vk, message):
    """Отправляет сообщение пользователю ВКонтакте."""
    vk.messages.send(
        user_id=int(VK_USER_ID),
        message=message,
        random_id=0
    )
    logging.debug('Успешно отправлено сообщение в VK: %s', message)


def get_api_answer(timestamp):
    """Запрашивает статусы домашних работ у API Практикума."""
    params = {'from_date': timestamp}

    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params=params,
            timeout=15
        )
    except requests.RequestException as error:
        raise ConnectionError(
            f'Не удалось запросить API: {error}'
        ) from error

    if response.status_code != 200:
        raise ConnectionError(
            f'API вернуло статус {response.status_code}'
        )

    return response.json()


def check_response(response):
    """Проверяет структуру ответа API."""
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарём.')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ homeworks.')

    if not isinstance(response['homeworks'], list):
        raise TypeError('Значение homeworks должно быть списком.')

    if 'current_date' not in response:
        raise KeyError('current_date')


def parse_status(homework):
    """Формирует сообщение об изменении статуса домашней работы."""
    try:
        homework_name = homework['homework_name']
        status = homework['status']
        verdict = HOMEWORK_VERDICTS[status]
    except (KeyError, TypeError) as error:
        raise ValueError(
            'В ответе API отсутствуют нужные данные '
            'или получен неизвестный статус.'
        ) from error

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        logging.critical('Не заданы обязательные переменные окружения.')
        raise SystemExit('Проверьте настройки в файле .env.')

    # Создаем сессию для бота
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    timestamp = int(time.time())

    logging.info('Бот запущен.')

    while True:
        try:

            response = get_api_answer(timestamp)
            check_response(response)

            if response['homeworks']:
                for homework in response['homeworks']:
                    message = parse_status(homework)
                    send_message(vk, message)
            else:
                logging.debug('Новых статусов домашних работ нет.')

            timestamp = response['current_date']

        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logging.error(message)
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
