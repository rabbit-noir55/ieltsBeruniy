from rest_framework import serializers

from .models import News, NewsComment, TestResult, TypingResult, User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['username', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        user = User(
            username=validated_data['username'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            role=User.ROLE_STUDENT,
            password_plain=validated_data['password'],
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'full_name', 'role', 'is_blocked']
        read_only_fields = ['id', 'username', 'role', 'is_blocked']


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


class NewsCommentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = NewsComment
        fields = ['id', 'news', 'user', 'text', 'created_at', 'can_delete']
        read_only_fields = ['id', 'news', 'user', 'created_at']

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return (
                obj.user_id == request.user.id
                or request.user.role == User.ROLE_TEACHER
            )
        return False


class NewsListSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True)
    dislike_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    read_count = serializers.IntegerField(read_only=True)
    my_reaction = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'excerpt', 'image_url', 'author', 'like_count',
            'dislike_count', 'comment_count', 'read_count',
            'my_reaction', 'published_at',
        ]

    def get_image_url(self, obj):
        if obj.image:
            url = obj.image.url
            request = self.context.get('request')
            return request.build_absolute_uri(url) if request else url
        return None

    def get_excerpt(self, obj):
        return obj.content[:200]

    def get_author(self, obj):
        if obj.created_by_id:
            return {
                'full_name': obj.created_by.get_full_name() or obj.created_by.username,
                'username': obj.created_by.username,
            }
        return None


class NewsDetailSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True)
    dislike_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    read_count = serializers.IntegerField(read_only=True)
    my_reaction = serializers.CharField(read_only=True, allow_null=True)
    comments = NewsCommentSerializer(many=True, read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'content', 'image_url', 'author', 'like_count',
            'dislike_count', 'comment_count', 'read_count',
            'my_reaction', 'comments', 'published_at',
        ]

    def get_image_url(self, obj):
        if obj.image:
            url = obj.image.url
            request = self.context.get('request')
            return request.build_absolute_uri(url) if request else url
        return None

    def get_author(self, obj):
        if obj.created_by_id:
            return {
                'full_name': obj.created_by.get_full_name() or obj.created_by.username,
                'username': obj.created_by.username,
            }
        return None
