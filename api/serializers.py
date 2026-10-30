from rest_framework import serializers

from .models import TestResult, TypingResult, User, UserGroup


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        email = validated_data['email'].lower().strip()
        user = User(
            email=email,
            username=email.split('@')[0],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            role=User.ROLE_STUDENT,
            password_plain=validated_data['password'],
        )
        user.set_password(validated_data['password'])
        user.save()  # save() will auto-generate unique username
        return user


class UserGroupSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(read_only=True, default=0)
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = UserGroup
        fields = ['id', 'name', 'slug', 'group_type', 'logo_url', 'parameters', 'user_count', 'ielts_date', 'schedule_type', 'schedule_time', 'description', 'competition_url']
        read_only_fields = ['id']

    def get_logo_url(self, obj):
        url = obj.logo_url
        if not url or url.startswith('data:'):
            return url or None
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class UserGroupBriefSerializer(serializers.ModelSerializer):
    """Short group info for embedding in UserSerializer."""
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = UserGroup
        fields = ['id', 'name', 'slug', 'group_type', 'logo_url', 'parameters', 'ielts_date', 'competition_url']

    def get_logo_url(self, obj):
        url = obj.logo_url
        if not url or url.startswith('data:'):
            return url or None
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    group_detail = UserGroupBriefSerializer(source='group', read_only=True)
    group_id = serializers.PrimaryKeyRelatedField(
        queryset=UserGroup.objects.all(),
        source='group',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'role', 'group', 'group_id', 'group_detail', 'is_blocked',
        ]
        read_only_fields = ['id', 'email', 'role', 'is_blocked']


class TestResultSerializer(serializers.ModelSerializer):
    student = UserSerializer(read_only=True)
    student_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.ROLE_STUDENT),
        source='student',
        write_only=True,
        required=False,
    )

    class Meta:
        model = TestResult
        fields = [
            'id', 'student', 'student_id', 'skill', 'series_id', 'test_num',
            'part_num', 'task_part', 'raw_score', 'total_questions', 'band',
            'answers', 'submitted_at', 'updated_at',
        ]
        read_only_fields = ['id', 'submitted_at', 'updated_at']


class TypingResultSerializer(serializers.ModelSerializer):
    student = UserSerializer(read_only=True)

    class Meta:
        model = TypingResult
        fields = [
            'id', 'student', 'mode', 'duration_seconds', 'wpm', 'accuracy',
            'characters', 'errors', 'created_at',
        ]
        read_only_fields = ['id', 'student', 'created_at']

    def validate(self, attrs):
        attrs['wpm'] = round(float(attrs['wpm']), 1)
        attrs['accuracy'] = round(float(attrs['accuracy']), 1)
        if attrs['wpm'] < 0 or attrs['wpm'] > 400:
            raise serializers.ValidationError({'wpm': 'wpm 0-400 oraligida bo\'lishi kerak.'})
        if attrs['accuracy'] < 0 or attrs['accuracy'] > 100:
            raise serializers.ValidationError({'accuracy': 'accuracy 0-100 oraligida bo\'lishi kerak.'})
        return attrs
