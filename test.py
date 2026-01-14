"""Simple test script for Ollama functionality."""

import requests


def test_ollama():
    """Send 'hello' to Ollama and print the response."""
    url = "http://10.112.165.53:11435/api/generate"

    payload = {
        "model": "llama3.2",  # 사용 가능한 모델명으로 변경 필요할 수 있음
        "prompt": "hello",
        "stream": False
    }

    try:
        print("Ollama 서버에 요청 중...")
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        print("\n=== 응답 ===")
        print(result.get("response", "응답 없음"))

    except requests.exceptions.ConnectionError:
        print(f"연결 실패: {url}에 연결할 수 없습니다.")
    except requests.exceptions.Timeout:
        print("요청 시간 초과")
    except requests.exceptions.RequestException as e:
        print(f"요청 오류: {e}")


if __name__ == "__main__":
    test_ollama()
