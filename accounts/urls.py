from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.AppLoginView.as_view(), name='login'),
    path('logout/', views.AppLogoutView.as_view(), name='logout'),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/update/', views.UserUpdateView.as_view(), name='user_update'),
    path('users/<int:pk>/deactivate/', views.UserDeactivateView.as_view(), name='user_deactivate'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),
    path('branches/', views.BranchListView.as_view(), name='branch_list'),
    path('branches/create/', views.BranchCreateView.as_view(), name='branch_create'),
    path('branches/<int:pk>/update/', views.BranchUpdateView.as_view(), name='branch_update'),
    path('branches/select/', views.BranchSelectView.as_view(), name='branch_select'),
]
