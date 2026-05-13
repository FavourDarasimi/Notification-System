from django.contrib.auth import logout
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import LoginSerializer, RegisterSerializer
from .tokens import generate_verification_token, verify_token

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        token = generate_verification_token(user.id)

        verification_link = f'http://127.0.0.1:8000/api/users/verify-email/{token}/'

        send_mail(
            subject='Verify your account',
            message=f'Click here to verify your account: {verification_link}',
            from_email=None,
            recipient_list=[user.email],
        )

        return Response(
            {
                'message': 'Registration successful. Check your email.'
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, token):
        user_id = verify_token(token)

        if not user_id:
            return Response(
                {'error': 'Invalid or expired token'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
            

        user = User.objects.get(id=user_id)
        if user.is_verified == True:
            return Response({
                'message':'User already verified'
            })
        user.is_verified = True
        user.save()

        return Response({'message': 'Email verified successfully'})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data)


class LogoutView(APIView):
    def post(self, request):
        try:
            refresh_token = request.data['refresh']

            token = RefreshToken(refresh_token)
            token.blacklist()

            logout(request)

            return Response({'message': 'Logged out successfully'})

        except Exception:
            return Response(
                {'error': 'Invalid token'},
                status=status.HTTP_400_BAD_REQUEST,
            )