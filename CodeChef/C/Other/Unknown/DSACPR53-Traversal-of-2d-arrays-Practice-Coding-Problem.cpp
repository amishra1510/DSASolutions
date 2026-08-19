Language: C++
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
#include <bits/stdc++.h>
using namespace std;
int main() {
    int N,M;
    cin >> N >> M;
        int arr[N][M];
        for(int i= 0 ; i<N; i++){
        for (int j = 0 ; j<M ; j++){
            cin >> arr[i][j];
        }
    }
        for(int i = 0 ; i<N ; i++){
        for (int j = 0; j<M; j++){
            cout<< arr[i][j]<<" ";
        }
        cout<<endl;
    }
            return 0;
}
