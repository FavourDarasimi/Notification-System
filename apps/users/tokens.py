from django.core import signing


def generate_verification_token(user_id):
    return signing.dumps(user_id)



def verify_token(token, max_age=3600):
    try:
        user_id = signing.loads(token, max_age=max_age)
        return user_id
    except signing.BadSignature:
        return None
    except signing.SignatureExpired:
        return None